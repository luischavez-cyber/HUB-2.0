"""Herramientas que el asistente de IA puede invocar.

Cada herramienta envuelve una función determinista de los módulos de la
plataforma. El modelo nunca calcula LMP ni dictámenes por su cuenta: los
obtiene de aquí, de modo que toda cifra normativa proviene del catálogo
NOM-138 y toda cifra analítica, de la base de datos del proyecto.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..dispersion import capitulo as capitulo5
from ..dispersion import medio_fisico as mf
from ..dispersion.analisis import analizar as analizar_dispersion
from ..exportacion.tablas import a_excel, a_word
from ..informe.generador import generar_y_registrar as generar_informe_completo
from ..informe.generador import verificacion_previa
from ..fotografia.clasificador import CATEGORIAS, MAX_PALABRAS, contar_palabras
from ..fotografia.registro import actualizar_fotografia, clasificar_fotografias, listar_fotografias
from ..fotografia.seccion import generar_word as seccion_fotografica_word
from ..laboratorio.captura import guardar_extraccion, importar_filas
from ..laboratorio.extractor import extraer
from ..normativa.evaluacion import evaluar, resumen
from ..normativa.nom138 import NORMA, PARAMETROS, PRODUCTOS, REFERENCIAS, UNIDAD, UsoSuelo, parametros_requeridos
from ..proyectos import CAMPOS_FICHA, Proyecto, campos_faltantes
from ..revision import dictamen
from ..revision.indice import CATEGORIAS as CATEGORIAS_HALLAZGO
from ..revision.indice import CRITICIDADES, calcular_ict
from ..revision.registro import ESTADOS, actualizar_hallazgo, hallazgos_de, listar_revisiones, revisar_borrador
from ..tablero import MODULOS, estado


@dataclass
class Contexto:
    """Estado compartido entre el asistente y la interfaz."""

    usuario: str = "asistente"
    proyecto: str | None = None
    archivos_generados: list[Path] = field(default_factory=list)
    cliente: Any = None  # cliente de la API para herramientas que usan visión

    def abrir(self) -> Proyecto:
        if not self.proyecto:
            raise ErrorHerramienta("No hay proyecto activo. Use listar_proyectos y seleccionar_proyecto, "
                                   "o crear_proyecto.")
        return Proyecto.abrir(self.proyecto, self.usuario)


class ErrorHerramienta(Exception):
    pass


def _obj(props: dict[str, Any], requeridos: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": requeridos or [], "additionalProperties": False}


_S = {"type": "string"}
_USOS = {"type": "array", "items": {"type": "string", "enum": [u.value for u in UsoSuelo]}}

DEFINICIONES: list[dict[str, Any]] = [
    {"name": "listar_proyectos", "description": "Lista los proyectos registrados en la plataforma.",
     "input_schema": _obj({})},
    {"name": "seleccionar_proyecto", "description": "Activa un proyecto por su clave para trabajar sobre él.",
     "input_schema": _obj({"clave": _S}, ["clave"])},
    {"name": "crear_proyecto",
     "description": "Crea un proyecto nuevo con su propio espacio de trabajo y lo deja activo.",
     "input_schema": _obj({"nombre": _S, "cliente": _S}, ["nombre"])},
    {"name": "consultar_ficha",
     "description": "Devuelve la ficha del proyecto activo (cliente, sitio, contaminante, uso de suelo, "
                    "responsable, expediente…) y los campos requeridos que faltan.",
     "input_schema": _obj({})},
    {"name": "actualizar_ficha",
     "description": "Actualiza campos de la ficha del proyecto activo. Solo use datos que el usuario haya "
                    "proporcionado. 'producto' debe ser un producto de la Tabla 1 de la NOM-138; "
                    "'usos_suelo' es una lista (más de uno = uso mixto).",
     "input_schema": _obj({
         **{c.clave: _S for c in CAMPOS_FICHA if c.clave not in ("usos_suelo", "producto")},
         "producto": {"type": "string", "enum": list(PRODUCTOS)},
         "usos_suelo": _USOS,
     })},
    {"name": "estado_proyecto",
     "description": "Tablero del proyecto activo: avance de cada módulo, conteos y alertas pendientes.",
     "input_schema": _obj({})},
    {"name": "consultar_norma",
     "description": f"Consulta el catálogo normativo {NORMA}: LMP por parámetro y uso de suelo (Tablas 2 y 3), "
                    "parámetros requeridos por producto (Tabla 1) y referencias. Única fuente válida de LMP.",
     "input_schema": _obj({"parametro": _S, "producto": _S, "usos_suelo": _USOS})},
    {"name": "consultar_resultados",
     "description": "Resultados de laboratorio guardados en el proyecto activo, con punto, zona, profundidad, "
                    "coordenadas UTM, método y página del PDF de origen. Filtros opcionales.",
     "input_schema": _obj({"zona": _S, "muestra": _S, "parametro": _S})},
    {"name": "evaluar_nom138",
     "description": "Evalúa los resultados del proyecto activo contra los LMP de la NOM-138 según su uso de "
                    "suelo (uso mixto: el más estricto). Devuelve resumen y dictamen por muestra.",
     "input_schema": _obj({"zona": _S, "solo_excedencias": {"type": "boolean"}})},
    {"name": "listar_documentos", "description": "Documentos cargados al proyecto activo (PDF de laboratorio, etc.).",
     "input_schema": _obj({"tipo": _S})},
    {"name": "extraer_pdf_laboratorio",
     "description": "Extrae con pdfplumber los resultados de un PDF de laboratorio ya cargado al proyecto. "
                    "Con guardar=false solo muestra la vista previa; con guardar=true los guarda en la base.",
     "input_schema": _obj({"documento_id": {"type": "integer"}, "guardar": {"type": "boolean"}},
                          ["documento_id", "guardar"])},
    {"name": "registrar_resultados",
     "description": "Captura o corrige manualmente filas de resultados (una por parámetro). Solo con datos "
                    "dictados por el usuario o leídos del documento oficial; nunca estimados.",
     "input_schema": _obj({"filas": {"type": "array", "items": _obj({
         "muestra": _S, "punto": _S, "zona": _S, "profundidad_m": _S, "utm_x": {"type": "number"},
         "utm_y": {"type": "number"}, "utm_zona": _S, "fecha_muestreo": _S, "parametro": _S,
         "valor": _S, "limite_deteccion": {"type": "number"}, "metodo": _S, "pagina_pdf": {"type": "integer"},
     }, ["muestra"])}}, ["filas"])},
    {"name": "exportar_evaluacion",
     "description": "Genera la tabla de cumplimiento NOM-138 en Excel o Word (lista para el informe).",
     "input_schema": _obj({"formato": {"type": "string", "enum": ["excel", "word"]}, "zona": _S}, ["formato"])},
    {"name": "crear_version",
     "description": "Guarda una instantánea de la base del proyecto (control de versiones).",
     "input_schema": _obj({"etiqueta": _S}, ["etiqueta"])},
    {"name": "listar_fotografias",
     "description": "Fotografías del proyecto activo con categoría, pie de foto, número de palabras, confianza de "
                    "la IA, si ya fue revisada por una persona, punto de muestreo asociado y fecha de toma.",
     "input_schema": _obj({"categoria": {"type": "string", "enum": list(CATEGORIAS)}})},
    {"name": "clasificar_fotografias",
     "description": "Clasifica con visión artificial las fotografías y genera pies técnicos de máximo "
                    f"{MAX_PALABRAS} palabras. Sin 'ids' procesa solo las pendientes. No pisa correcciones "
                    "manuales salvo forzar=true.",
     "input_schema": _obj({"ids": {"type": "array", "items": {"type": "integer"}}, "forzar": {"type": "boolean"}})},
    {"name": "actualizar_fotografia",
     "description": "Reclasifica o corrige una fotografía: categoría, pie (máx. 15 palabras), punto de muestreo, "
                    "orden dentro de su categoría, si se incluye en el informe y si quedó revisada.",
     "input_schema": _obj({"id": {"type": "integer"}, "categoria": {"type": "string", "enum": list(CATEGORIAS)},
                           "pie": _S, "punto": _S, "orden": {"type": "integer"}, "incluir": {"type": "boolean"},
                           "revisada": {"type": "boolean"}}, ["id"])},
    {"name": "generar_seccion_fotografica",
     "description": "Genera en Word la sección fotográfica ordenada por categoría y numerada, lista para el informe.",
     "input_schema": _obj({"titulo": _S})},
    {"name": "listar_borradores",
     "description": "Borradores del informe cargados al proyecto y sus revisiones técnicas (ICT original y vigente).",
     "input_schema": _obj({})},
    {"name": "revisar_informe",
     "description": "Revisión técnica del borrador desde la perspectiva de SEMARNAT/ASEA: verificaciones automáticas "
                    "contra la base del proyecto y la NOM-138 y, con usar_ia=true, revisión completa con IA. Guarda "
                    "la revisión y devuelve el Índice de Calidad Técnica (0-100) y el conteo de hallazgos.",
     "input_schema": _obj({"documento_id": {"type": "integer"}, "usar_ia": {"type": "boolean"}}, ["documento_id"])},
    {"name": "consultar_revision",
     "description": "Hallazgos de una revisión (por omisión, la más reciente), con filtros por criticidad y estado.",
     "input_schema": _obj({"revision_id": {"type": "integer"},
                           "criticidad": {"type": "string", "enum": list(CRITICIDADES)},
                           "estado": {"type": "string", "enum": list(ESTADOS)}})},
    {"name": "actualizar_hallazgo",
     "description": "Marca un hallazgo como atendido, descartado (requiere justificación en la nota) o abierto. "
                    "Solo con confirmación del usuario.",
     "input_schema": _obj({"id": {"type": "integer"}, "estado": {"type": "string", "enum": list(ESTADOS)},
                           "nota": _S}, ["id", "estado"])},
    {"name": "exportar_revision",
     "description": "Genera el dictamen de revisión técnica en Word o la matriz de hallazgos en Excel.",
     "input_schema": _obj({"revision_id": {"type": "integer"},
                           "formato": {"type": "string", "enum": ["word", "excel"]}}, ["formato"])},
    {"name": "consultar_medio_fisico",
     "description": "Datos del medio físico del sitio (topografía, suelo, geología, hidrología, vegetación, clima, "
                    "evento) con su fuente, y los datos requeridos faltantes o sin fuente.",
     "input_schema": _obj({})},
    {"name": "actualizar_medio_fisico",
     "description": "Registra datos del medio físico. Cada dato exige su fuente documental (levantamiento de campo, "
                    "carta temática, estación climatológica, informe…). Solo datos y fuentes que dé el usuario o que "
                    "consten en un documento del proyecto; nunca estimados.",
     "input_schema": _obj({"datos": {"type": "object", "additionalProperties": False, "properties": {
         c.clave: {"type": "object", "additionalProperties": False, "required": ["valor", "fuente"],
                   "description": c.etiqueta + (f" ({c.unidad})" if c.unidad else "")
                   + (f"; opciones: {', '.join(c.opciones)}" if c.opciones else ""),
                   "properties": {"valor": {"type": ["string", "number"]}, "fuente": _S, "observacion": _S}}
         for c in mf.CAMPOS}}}, ["datos"])},
    {"name": "analizar_dispersion",
     "description": "Análisis determinista de la dispersión: distribución espacial y vertical de la afectación, "
                    "dirección respecto a la pendiente, área y volumen preliminar, delimitación, matriz de "
                    "susceptibilidad, receptores e información faltante.",
     "input_schema": _obj({})},
    {"name": "generar_capitulo5",
     "description": "Genera el Capítulo 5 (Análisis de dispersión de hidrocarburos) en Word con tablas y figura. "
                    "Con usar_ia=true lo redacta con IA y marca las cifras sin respaldo en los datos.",
     "input_schema": _obj({"usar_ia": {"type": "boolean"}})},
    {"name": "verificar_insumos_informe",
     "description": "Verificación previa a la generación del informe: estado de ficha, resultados, fotografías, "
                    "medio físico, Capítulo 5, delimitación y última revisión técnica.",
     "input_schema": _obj({})},
    {"name": "generar_informe",
     "description": "Genera el Informe de Caracterización completo en Word (portada, índice, capítulos 1 a 10 y "
                    "anexos) con los datos de todos los módulos, opcionalmente sobre la plantilla Word de CAEPSA "
                    "(documento tipo plantilla_word). Lo guarda como borrador y, con revisar=true, le aplica la "
                    "revisión técnica automática. Lo no sustentado por datos queda como [COMPLETAR: …].",
     "input_schema": _obj({"plantilla_id": {"type": "integer"}, "revisar": {"type": "boolean"}})},
    {"name": "consultar_bitacora", "description": "Últimos cambios registrados (quién, cuándo, antes/después).",
     "input_schema": _obj({"limite": {"type": "integer"}})},
]


# ---------------------------------------------------------------------- implementación
def _listar_proyectos(ctx: Contexto) -> Any:
    return {"activo": ctx.proyecto, "proyectos": Proyecto.listar()}


def _seleccionar_proyecto(ctx: Contexto, clave: str) -> Any:
    Proyecto.abrir(clave)
    ctx.proyecto = clave
    return {"activo": clave}


def _crear_proyecto(ctx: Contexto, nombre: str, cliente: str = "") -> Any:
    p = Proyecto.crear(nombre, usuario=ctx.usuario, cliente=cliente)
    ctx.proyecto = p.clave
    return {"creado": p.clave, "ruta": str(p.ruta)}


def _consultar_ficha(ctx: Contexto) -> Any:
    ficha = ctx.abrir().ficha()
    return {"ficha": ficha, "faltantes": [c.etiqueta for c in campos_faltantes(ficha)]}


def _actualizar_ficha(ctx: Contexto, **cambios: Any) -> Any:
    if not cambios:
        raise ErrorHerramienta("No se indicó ningún campo")
    p = ctx.abrir()
    p.actualizar_ficha(cambios)
    return {"actualizados": sorted(cambios)}


def _estado_proyecto(ctx: Contexto) -> Any:
    p = ctx.abrir()
    avance, alertas = estado(p)
    return {"conteos": p.conteos(),
            "avance": {f"{n}. {nombre}": f"{avance[n] * 100:.0f} %" for n, nombre in MODULOS},
            "alertas": [{"nivel": a.nivel, "modulo": a.modulo, "mensaje": a.mensaje} for a in alertas]}


def _consultar_norma(ctx: Contexto, parametro: str | None = None, producto: str | None = None,
                     usos_suelo: list[str] | None = None) -> Any:
    from ..normativa.nom138 import identificar_parametro

    out: dict[str, Any] = {"norma": NORMA, "unidad": UNIDAD, "referencias": REFERENCIAS}
    claves = list(PARAMETROS)
    if parametro:
        c = parametro.upper() if parametro.upper() in PARAMETROS else identificar_parametro(parametro)
        if not c:
            raise ErrorHerramienta(f"'{parametro}' no tiene LMP en la {NORMA}")
        claves = [c]
    usos = [UsoSuelo(u) for u in usos_suelo] if usos_suelo else list(UsoSuelo)
    out["lmp"] = [{"clave": c, "parametro": PARAMETROS[c].nombre, "tabla": PARAMETROS[c].tabla,
                   **{u.etiqueta: PARAMETROS[c].lmp[u] for u in usos},
                   **({"lmp_aplicable_uso_mixto": min(PARAMETROS[c].lmp[u] for u in usos)} if len(usos) > 1 and
                      usos_suelo else {})} for c in claves]
    if producto:
        if producto not in PRODUCTOS:
            raise ErrorHerramienta(f"Producto no contemplado en la Tabla 1. Opciones: {', '.join(PRODUCTOS)}")
        out["parametros_requeridos_tabla1"] = [PARAMETROS[c].nombre for c in parametros_requeridos(producto)]
    return out


def _filtrar(filas: list[dict[str, Any]], zona: str | None = None, muestra: str | None = None,
             parametro: str | None = None) -> list[dict[str, Any]]:
    return [f for f in filas
            if (not zona or (f.get("zona") or "").lower() == zona.lower())
            and (not muestra or f.get("muestra") == muestra)
            and (not parametro or (f.get("parametro") or "").upper() == parametro.upper())]


def _consultar_resultados(ctx: Contexto, zona: str | None = None, muestra: str | None = None,
                          parametro: str | None = None) -> Any:
    filas = _filtrar(ctx.abrir().tabla_resultados(), zona, muestra, parametro)
    return {"total": len(filas), "filas": filas[:300], "truncado": len(filas) > 300}


def _evaluar(ctx: Contexto, zona: str | None = None) -> tuple[Proyecto, list[Any], list[UsoSuelo]]:
    p = ctx.abrir()
    usos = p.usos_suelo()
    if not usos:
        raise ErrorHerramienta("El proyecto no tiene uso de suelo definido; pídalo al usuario y use actualizar_ficha")
    filas = _filtrar(p.tabla_resultados(), zona)
    return p, evaluar(filas, usos, p.ficha().get("producto")), usos


def _evaluar_nom138(ctx: Contexto, zona: str | None = None, solo_excedencias: bool = False) -> Any:
    _, muestras, usos = _evaluar(ctx, zona)
    s = resumen(muestras)
    detalle = []
    for m in muestras:
        if solo_excedencias and not m.excedencias:
            continue
        detalle.append({
            "muestra": m.muestra, "punto": m.punto, "zona": m.zona, "dictamen": m.estado,
            "profundidad_m": m.datos.get("profundidad_m"), "utm_x": m.datos.get("utm_x"),
            "utm_y": m.datos.get("utm_y"), "parametros_faltantes_tabla1": m.faltantes,
            "resultados": [{"parametro": r.parametro, "valor": r.valor, "menor_que_LD": r.menor_que,
                            "lmp": r.lmp, "valor_entre_lmp": round(r.proporcion, 2) if r.proporcion else None,
                            "estado": r.estado, "referencia": r.referencia,
                            **({"observaciones": r.observaciones} if r.observaciones else {})}
                           for r in m.resultados],
        })
    return {"uso_suelo": [u.etiqueta for u in usos], "resumen": s, "muestras": detalle}


def _listar_documentos(ctx: Contexto, tipo: str | None = None) -> Any:
    return [{k: d[k] for k in ("id", "tipo", "nombre", "cargado")} for d in ctx.abrir().documentos(tipo)]


def _extraer_pdf(ctx: Contexto, documento_id: int, guardar: bool) -> Any:
    p = ctx.abrir()
    doc = next((d for d in p.documentos() if d["id"] == documento_id), None)
    if not doc:
        raise ErrorHerramienta(f"No existe el documento {documento_id}")
    ext = extraer(Path(doc["ruta"]))
    vista = [{"muestra": m.clave, "pagina": m.pagina, "punto": m.punto, "zona": m.zona,
              "profundidad_m": m.profundidad_m, "utm_x": m.utm_x, "utm_y": m.utm_y,
              "fecha_muestreo": m.fecha_muestreo,
              "resultados": {k: ("<" if r.menor_que else "") + (f"{r.valor:g}" if r.valor is not None else "ND")
                             for k, r in m.resultados.items()},
              "campos_por_capturar": m.faltantes} for m in ext.muestras]
    out: dict[str, Any] = {"paginas": ext.paginas, "muestras": len(vista), "advertencias": ext.advertencias,
                           "metodos": ext.metodos, "vista_previa": vista}
    if guardar:
        out["resultados_guardados"] = guardar_extraccion(p, ext, utm_zona=p.ficha().get("utm_zona"))
    return out


def _registrar_resultados(ctx: Contexto, filas: list[dict[str, Any]]) -> Any:
    errores = importar_filas(ctx.abrir(), filas, origen="asistente")
    return {"filas": len(filas), "errores": errores}


def _exportar(ctx: Contexto, formato: str, zona: str | None = None) -> Any:
    p, muestras, usos = _evaluar(ctx, zona)
    if not muestras:
        raise ErrorHerramienta("No hay resultados que exportar")
    ficha = p.ficha()
    contenido, ext = (a_excel(muestras, usos, ficha), "xlsx") if formato == "excel" else \
        (a_word(muestras, usos, ficha), "docx")
    destino = p.ruta / "archivos" / "exportaciones" / f"{p.clave}_NOM138{'_' + zona if zona else ''}.{ext}"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(contenido)
    ctx.archivos_generados.append(destino)
    return {"archivo": destino.name, "muestras": len(muestras)}


def _listar_fotografias(ctx: Contexto, categoria: str | None = None) -> Any:
    campos = ("id", "nombre", "categoria", "categoria_origen", "pie", "pie_origen", "confianza", "observacion",
              "punto", "fecha_toma", "orden", "revisada", "incluir")
    return [{**{k: f[k] for k in campos}, "palabras": contar_palabras(f["pie"] or "")}
            for f in listar_fotografias(ctx.abrir(), categoria)]


def _clasificar_fotografias(ctx: Contexto, ids: list[int] | None = None, forzar: bool = False) -> Any:
    return clasificar_fotografias(ctx.abrir(), cliente=ctx.cliente, ids=ids, forzar=forzar)


def _actualizar_fotografia(ctx: Contexto, id: int, **campos: Any) -> Any:
    if campos.get("pie") and contar_palabras(campos["pie"]) > MAX_PALABRAS:
        raise ErrorHerramienta(f"El pie tiene {contar_palabras(campos['pie'])} palabras; máximo {MAX_PALABRAS}")
    for k in ("incluir", "revisada"):
        if k in campos:
            campos[k] = int(bool(campos[k]))
    return {"cambios": actualizar_fotografia(ctx.abrir(), id, origen="asistente", **campos)}


def _seccion_fotografica(ctx: Contexto, titulo: str = "Memoria fotográfica") -> Any:
    p = ctx.abrir()
    contenido, avisos = seccion_fotografica_word(p, titulo)
    destino = p.ruta / "archivos" / "exportaciones" / f"{p.clave}_seccion_fotografica.docx"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(contenido)
    ctx.archivos_generados.append(destino)
    return {"archivo": destino.name, "avisos": avisos}


def _listar_borradores(ctx: Contexto) -> Any:
    p = ctx.abrir()
    revs = listar_revisiones(p)
    return [{"documento_id": d["id"], "nombre": d["nombre"], "cargado": d["cargado"],
             "revisiones": [{"revision_id": r["id"], "fecha": r["fecha"], "ict": r["ict"],
                             "ict_vigente": r["ict_vigente"], "usa_ia": bool(r["usa_ia"])}
                            for r in revs if r["documento_id"] == d["id"]]}
            for d in p.documentos("borrador")]


def _revisar_informe(ctx: Contexto, documento_id: int, usar_ia: bool = True) -> Any:
    p = ctx.abrir()
    rev_id = revisar_borrador(p, documento_id, usar_ia=usar_ia, cliente=ctx.cliente if usar_ia else None)
    rev = next(r for r in listar_revisiones(p) if r["id"] == rev_id)
    hs = hallazgos_de(p, rev_id)
    return {"revision_id": rev_id, "ict": rev["ict"], "interpretacion": rev["interpretacion"],
            "subindices": rev["subindices"], "aviso": rev["aviso"],
            "hallazgos_por_criticidad": {c: sum(1 for h in hs if h.criticidad == c) for c in CRITICIDADES},
            "resumen_ia": rev["resumen"]}


def _revision(ctx: Contexto, revision_id: int | None) -> tuple[Proyecto, dict[str, Any]]:
    p = ctx.abrir()
    revs = listar_revisiones(p)
    if not revs:
        raise ErrorHerramienta("No hay revisiones; use revisar_informe")
    rev = revs[0] if revision_id is None else next((r for r in revs if r["id"] == revision_id), None)
    if rev is None:
        raise ErrorHerramienta(f"No existe la revisión {revision_id}")
    return p, rev


def _consultar_revision(ctx: Contexto, revision_id: int | None = None, criticidad: str | None = None,
                        estado: str | None = None) -> Any:
    p, rev = _revision(ctx, revision_id)
    hs = hallazgos_de(p, rev["id"])
    return {"revision_id": rev["id"], "documento": rev["documento"], "ict_vigente": calcular_ict(hs)["ict"],
            "hallazgos": [{"id": h.id, "origen": h.origen, "criticidad": h.criticidad,
                           "categoria": CATEGORIAS_HALLAZGO[h.categoria][0], "ubicacion": h.ubicacion,
                           "descripcion": h.descripcion, "evidencia": h.evidencia[:300],
                           "evidencia_localizada": h.evidencia_localizada, "riesgo": h.riesgo,
                           "recomendacion": h.recomendacion, "referencia": h.referencia, "estado": h.estado,
                           "nota": h.nota}
                          for h in hs if (not criticidad or h.criticidad == criticidad)
                          and (not estado or h.estado == estado)]}


def _actualizar_hallazgo(ctx: Contexto, id: int, estado: str, nota: str = "") -> Any:
    actualizar_hallazgo(ctx.abrir(), id, estado, nota)
    return {"id": id, "estado": estado}


def _exportar_revision(ctx: Contexto, formato: str, revision_id: int | None = None) -> Any:
    p, rev = _revision(ctx, revision_id)
    contenido, ext, sufijo = ((dictamen.a_word(p, rev["id"]), "docx", "dictamen") if formato == "word"
                              else (dictamen.a_excel(p, rev["id"]), "xlsx", "hallazgos"))
    destino = p.ruta / "archivos" / "exportaciones" / f"{p.clave}_revision{rev['id']}_{sufijo}.{ext}"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(contenido)
    ctx.archivos_generados.append(destino)
    return {"archivo": destino.name}


def _consultar_medio_fisico(ctx: Contexto) -> Any:
    datos = mf.leer(ctx.abrir())
    falt = mf.faltantes(datos)
    return {"datos": {k: {"grupo": mf.POR_CLAVE[k].grupo, "etiqueta": mf.POR_CLAVE[k].etiqueta, "valor": d["valor"],
                          "unidad": mf.POR_CLAVE[k].unidad, "fuente": d["fuente"]}
                      for k, d in datos.items() if k in mf.POR_CLAVE},
            "requeridos_sin_valor": [c.etiqueta for c in falt["sin_valor"]],
            "sin_fuente_no_utilizables": [c.etiqueta for c in falt["sin_fuente"]]}


def _actualizar_medio_fisico(ctx: Contexto, datos: dict[str, dict[str, Any]]) -> Any:
    sin_fuente = [k for k, d in datos.items() if not str(d.get("fuente") or "").strip()]
    if sin_fuente:
        raise ErrorHerramienta(f"Falta la fuente de: {', '.join(sin_fuente)}. Pídala al usuario.")
    return {"actualizados": mf.guardar(ctx.abrir(), datos)}


def _analizar_dispersion(ctx: Contexto) -> Any:
    return capitulo5.hechos(analizar_dispersion(ctx.abrir()))


def _generar_capitulo5(ctx: Contexto, usar_ia: bool = True) -> Any:
    p = ctx.abrir()
    aid = capitulo5.generar(p, usar_ia=usar_ia, cliente=ctx.cliente if usar_ia else None)
    r = capitulo5.obtener(p, aid)
    destino = p.ruta / "archivos" / "exportaciones" / f"{p.clave}_capitulo5_v{aid}.docx"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(capitulo5.a_word(p, aid))
    ctx.archivos_generados.append(destino)
    return {"analisis_id": aid, "archivo": destino.name, "redactado_con_ia": bool(r["usa_ia"]), "aviso": r["aviso"],
            "cifras_no_respaldadas": r["cifras_no_respaldadas"],
            "pendientes": r["metricas"].get("pendientes", [])}


def _verificar_insumos_informe(ctx: Contexto) -> Any:
    return verificacion_previa(ctx.abrir())


def _generar_informe(ctx: Contexto, plantilla_id: int | None = None, revisar: bool = True) -> Any:
    r = generar_informe_completo(ctx.abrir(), plantilla_id=plantilla_id, revisar=revisar)
    ctx.archivos_generados.append(Path(r["ruta"]))
    pendientes = r.pop("pendientes")
    r.pop("ruta")
    return {**r, "datos_por_completar": len(pendientes), "ejemplos_por_completar": list(dict.fromkeys(pendientes))[:15]}


def _crear_version(ctx: Contexto, etiqueta: str) -> Any:
    return {"version": ctx.abrir().crear_instantanea(etiqueta).name}


def _consultar_bitacora(ctx: Contexto, limite: int = 30) -> Any:
    return ctx.abrir().bitacora(min(max(limite, 1), 200))


IMPLEMENTACIONES: dict[str, Callable[..., Any]] = {
    "listar_proyectos": _listar_proyectos,
    "seleccionar_proyecto": _seleccionar_proyecto,
    "crear_proyecto": _crear_proyecto,
    "consultar_ficha": _consultar_ficha,
    "actualizar_ficha": _actualizar_ficha,
    "estado_proyecto": _estado_proyecto,
    "consultar_norma": _consultar_norma,
    "consultar_resultados": _consultar_resultados,
    "evaluar_nom138": _evaluar_nom138,
    "listar_documentos": _listar_documentos,
    "extraer_pdf_laboratorio": _extraer_pdf,
    "registrar_resultados": _registrar_resultados,
    "exportar_evaluacion": _exportar,
    "listar_fotografias": _listar_fotografias,
    "clasificar_fotografias": _clasificar_fotografias,
    "actualizar_fotografia": _actualizar_fotografia,
    "generar_seccion_fotografica": _seccion_fotografica,
    "listar_borradores": _listar_borradores,
    "revisar_informe": _revisar_informe,
    "consultar_revision": _consultar_revision,
    "actualizar_hallazgo": _actualizar_hallazgo,
    "exportar_revision": _exportar_revision,
    "consultar_medio_fisico": _consultar_medio_fisico,
    "actualizar_medio_fisico": _actualizar_medio_fisico,
    "analizar_dispersion": _analizar_dispersion,
    "generar_capitulo5": _generar_capitulo5,
    "verificar_insumos_informe": _verificar_insumos_informe,
    "generar_informe": _generar_informe,
    "crear_version": _crear_version,
    "consultar_bitacora": _consultar_bitacora,
}
assert set(IMPLEMENTACIONES) == {d["name"] for d in DEFINICIONES}


def ejecutar(ctx: Contexto, nombre: str, entrada: dict[str, Any]) -> tuple[str, bool]:
    """Ejecuta una herramienta. Devuelve (JSON del resultado, es_error)."""
    fn = IMPLEMENTACIONES.get(nombre)
    if fn is None:
        return json.dumps({"error": f"Herramienta desconocida: {nombre}"}), True
    try:
        return json.dumps(fn(ctx, **entrada), ensure_ascii=False, default=str), False
    except (ErrorHerramienta, ValueError, KeyError, TypeError) as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False), True
