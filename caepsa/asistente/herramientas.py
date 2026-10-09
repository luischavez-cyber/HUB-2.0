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

from ..exportacion.tablas import a_excel, a_word
from ..laboratorio.captura import guardar_extraccion, importar_filas
from ..laboratorio.extractor import extraer
from ..normativa.evaluacion import evaluar, resumen
from ..normativa.nom138 import NORMA, PARAMETROS, PRODUCTOS, REFERENCIAS, UNIDAD, UsoSuelo, parametros_requeridos
from ..proyectos import CAMPOS_FICHA, Proyecto, campos_faltantes
from ..tablero import MODULOS, estado


@dataclass
class Contexto:
    """Estado compartido entre el asistente y la interfaz."""

    usuario: str = "asistente"
    proyecto: str | None = None
    archivos_generados: list[Path] = field(default_factory=list)

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
