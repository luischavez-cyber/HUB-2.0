"""Verificaciones automáticas del borrador contra la base del proyecto y el catálogo NOM-138.

Solo se reporta lo que puede demostrarse con el documento y los datos cargados; cada hallazgo incluye
la cita o celda que lo origina.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from ..laboratorio.extractor import interpretar_valor
from ..normativa.evaluacion import EXCEDE, MuestraEvaluada, evaluar
from ..normativa.nom138 import NORMA, PARAMETROS, UsoSuelo, identificar_parametro, lmp_aplicable
from ..proyectos import Proyecto
from .documento import Bloque, Documento, normalizar
from .indice import Hallazgo

# Secciones esperadas (estructura definida por CAEPSA para el Informe de Caracterización).
SECCIONES_ESPERADAS: dict[str, tuple[str, tuple[str, ...]]] = {
    "antecedentes": ("Antecedentes", ("antecedente",)),
    "marco_legal": ("Marco legal", ("marco legal", "marco juridico", "marco normativo")),
    "metodologia": ("Metodología de muestreo", ("metodologia", "muestreo")),
    "resultados": ("Resultados", ("resultado",)),
    "pluma": ("Identificación de la pluma contaminante", ("pluma", "extension de la afectacion",
                                                          "delimitacion", "area afectada")),
    "danos": ("Evaluación de daños", ("dano", "danos", "afectacion")),
    "conclusiones": ("Conclusiones", ("conclusion",)),
    "saneamiento": ("Plan de saneamiento", ("saneamiento", "remediacion")),
    "fotografico": ("Sección fotográfica", ("fotografic", "memoria fotografica", "anexo fotografico")),
}

_RE_NOM138_VIGENTE = re.compile(r"NOM[\s-]*138[\s-]*SEMARNAT\s*/\s*SSA1[\s-]*2012", re.I)
_RE_NOM138_2003 = re.compile(r"NOM[\s-]*138[\s-]*SEMARNAT\s*/\s*SS[\s-]*2003", re.I)
_RE_NOM_OTRAS = re.compile(r"\bNOM[\s-]*(\d{3})[\s-]*[A-Z0-9]+(?:\s*/\s*[A-Z0-9]+)*[\s-]*(\d{4})\b", re.I)
_RE_FECHA_NUM = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
_RE_FECHA_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MESES = {m: i for i, m in enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
     "noviembre", "diciembre"], start=1)}
_RE_FECHA_TEXTO = re.compile(r"\b(\d{1,2})\s+de\s+(" + "|".join(_MESES) + r")\s+(?:de|del)\s+(\d{4})\b", re.I)
_USOS_TEXTO = {
    "agricola": UsoSuelo.AGRICOLA, "forestal": UsoSuelo.AGRICOLA, "pecuario": UsoSuelo.AGRICOLA,
    "conservacion": UsoSuelo.AGRICOLA, "residencial": UsoSuelo.RESIDENCIAL, "recreativo": UsoSuelo.RESIDENCIAL,
    "industrial": UsoSuelo.INDUSTRIAL, "comercial": UsoSuelo.INDUSTRIAL,
}


def _oracion(texto: str, inicio: int, fin: int) -> str:
    a = max(texto.rfind(".", 0, inicio), texto.rfind("\n", 0, inicio)) + 1
    b_punto, b_salto = texto.find(".", fin), texto.find("\n", fin)
    b = min(x for x in (b_punto, b_salto, len(texto)) if x != -1)
    return texto[a:b + 1].strip()[:400]


def _buscar(doc: Documento, patron: re.Pattern[str]) -> list[tuple[Bloque, re.Match[str]]]:
    return [(b, m) for b in doc.bloques if b.tipo != "tabla" for m in patron.finditer(b.texto)]


# --------------------------------------------------------------------------- normativa y unidades
def verificar_normativa(doc: Documento) -> list[Hallazgo]:
    h: list[Hallazgo] = []
    todo = "\n".join(b.texto for b in doc.bloques)
    if not _RE_NOM138_VIGENTE.search(todo):
        h.append(Hallazgo(
            "automatica", "vacio_regulatorio", "critica", "Documento completo",
            f"El informe no cita la {NORMA}, marco de referencia para los LMP y la caracterización del sitio.",
            riesgo="La autoridad puede considerar que la evaluación carece de sustento normativo.",
            recomendacion=f"Citar la {NORMA} en el marco legal y en la comparación de resultados.",
            referencia=NORMA))
    for b, m in _buscar(doc, _RE_NOM138_2003):
        h.append(Hallazgo(
            "automatica", "referencia_normativa", "alta", b.ubicacion,
            "Se cita la NOM-138-SEMARNAT/SS-2003, versión sustituida por la NOM-138-SEMARNAT/SSA1-2012.",
            evidencia=_oracion(b.texto, m.start(), m.end()),
            riesgo="Uso de LMP o criterios no vigentes.",
            recomendacion=f"Sustituir la referencia por la {NORMA} y revisar los LMP utilizados.",
            referencia=NORMA, evidencia_localizada=True))
    otras = sorted({re.sub(r"\s+", "", m.group(0)).upper() for _, m in _buscar(doc, _RE_NOM_OTRAS)
                    if m.group(1) != "138"})
    if otras:
        h.append(Hallazgo(
            "automatica", "referencia_normativa", "info", "Documento completo",
            "Se citan normas distintas a la NOM-138: " + ", ".join(otras) + ". Verifique su pertinencia; la "
            "evaluación de cumplimiento de este informe se sustenta en la NOM-138.",
            recomendacion="Conservar solo las referencias aplicables y no usarlas como fuente de LMP de suelo."))
    texto = normalizar(todo)
    if re.search(r"\bppm\b", texto):
        h.append(Hallazgo(
            "automatica", "ambiguo", "baja", "Documento completo",
            "Se usan «ppm» como unidad; la NOM-138 expresa los LMP en mg/kg base seca.",
            recomendacion="Expresar todas las concentraciones en mg/kg base seca."))
    if "mg/kg" in texto and "base seca" not in texto:
        h.append(Hallazgo(
            "automatica", "ambiguo", "baja", "Documento completo",
            "No se indica que las concentraciones se reportan en base seca.",
            recomendacion="Indicar «mg/kg base seca» en tablas y texto de resultados."))
    return h


# --------------------------------------------------------------------------- estructura
def verificar_estructura(doc: Documento, hay_excedencias: bool) -> list[Hallazgo]:
    h: list[Hallazgo] = []
    titulos = [normalizar(b.texto) for b in doc.titulos]
    for clave, (nombre, claves) in SECCIONES_ESPERADAS.items():
        if any(k in t for t in titulos for k in claves):
            continue
        critic = "alta" if clave in ("resultados", "metodologia", "conclusiones") or (
            clave == "saneamiento" and hay_excedencias) else "media"
        h.append(Hallazgo(
            "automatica", "estructura", critic, "Índice del documento",
            f"No se identifica la sección «{nombre}».",
            riesgo="Información requerida por la estructura del informe de caracterización ausente o no localizable.",
            recomendacion=f"Incluir la sección «{nombre}» con título explícito."))
    texto = normalizar(doc.texto + "\n" + "\n".join(b.texto for b in doc.tablas))
    if "cadena de custodia" not in texto:
        h.append(Hallazgo(
            "automatica", "insuficiente", "media", "Metodología / anexos",
            "No se menciona la cadena de custodia de las muestras.",
            riesgo="Se puede cuestionar la trazabilidad de las muestras analizadas.",
            recomendacion="Describir y anexar las cadenas de custodia firmadas."))
    if "acreditad" not in texto:
        h.append(Hallazgo(
            "automatica", "insuficiente", "media", "Metodología / resultados",
            "No se documenta la acreditación del laboratorio que realizó los análisis.",
            riesgo="La autoridad puede no reconocer resultados de un laboratorio sin acreditación demostrada.",
            recomendacion="Indicar la acreditación vigente del laboratorio y anexar el informe de resultados oficial.",
            referencia=f"{NORMA} (verificar apartado sobre laboratorios)"))
    return h


# --------------------------------------------------------------------------- conteos
def verificar_conteos(doc: Documento, n_muestras: int, n_puntos: int) -> list[Hallazgo]:
    h: list[Hallazgo] = []
    # Menciones calificadas («5 puntos con excedencia», «7 muestras exceden») son subconjuntos, no totales.
    calificador = (r"(?!(?:\s+de\s+muestreo)?\s+(?:por|en cada|de cada|con|que|donde|exced|super|rebas|cumpl|present|"
                   r"indeterminad|de la periferia|adicional))")
    for etiqueta, patron, real in (
        ("muestras", re.compile(rf"\b(\d{{1,3}})\s+muestras\b{calificador}", re.I), n_muestras),
        ("puntos de muestreo", re.compile(rf"\b(\d{{1,3}})\s+puntos(?:\s+de\s+muestreo)?\b{calificador}", re.I),
         n_puntos),
    ):
        menciones = [(b, m, int(m.group(1))) for b, m in _buscar(doc, patron)]
        valores = sorted({v for _, _, v in menciones})
        if len(valores) > 1:
            b, m, _ = menciones[0]
            h.append(Hallazgo(
                "automatica", "contradictorio", "alta", ", ".join(sorted({x.ubicacion for x, _, _ in menciones})),
                f"El texto menciona cantidades distintas de {etiqueta}: {', '.join(map(str, valores))}.",
                evidencia=_oracion(b.texto, m.start(), m.end()),
                recomendacion=f"Unificar el número de {etiqueta} en todo el documento.", evidencia_localizada=True))
        if real and valores and max(valores) != real:
            b, m, v = max(menciones, key=lambda x: x[2])
            h.append(Hallazgo(
                "automatica", "inconsistencia_laboratorio", "alta", b.ubicacion,
                f"El informe indica {v} {etiqueta}; la base del proyecto registra {real}.",
                evidencia=_oracion(b.texto, m.start(), m.end()),
                riesgo="Discrepancia entre el informe y los resultados de laboratorio.",
                recomendacion=f"Verificar el número de {etiqueta} contra el informe del laboratorio.",
                evidencia_localizada=True))
    return h


# --------------------------------------------------------------------------- tablas
def _num(texto: str) -> float | None:
    m = re.search(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-+]?\d+(?:\.\d+)?", texto or "")
    return float(m.group().replace(",", "")) if m else None


def _distinto(a: float, b: float) -> bool:
    return abs(a - b) > max(0.011, 0.01 * max(abs(a), abs(b)))


def _encabezado(filas: list[list[str]]) -> tuple[int, dict[int, str]] | None:
    for i, fila in enumerate(filas[:3]):
        cols = {j: clave for j, celda in enumerate(fila) if (clave := identificar_parametro(celda or ""))}
        if cols:
            return i, cols
    return None


def _col(cabecera: list[str], patron: str) -> int | None:
    rx = re.compile(patron, re.I)
    return next((j for j, c in enumerate(cabecera) if rx.search(normalizar(c))), None)


def verificar_tablas(doc: Documento, p: Proyecto, usos: list[UsoSuelo],
                     evaluadas: dict[str, MuestraEvaluada]) -> list[Hallazgo]:
    h: list[Hallazgo] = []
    resultados: dict[tuple[str, str], dict[str, Any]] = {}
    muestra_punto: dict[str, str | None] = {}
    for f in p.tabla_resultados():
        muestra_punto[normalizar(f["muestra"])] = f["punto"]
        if f["parametro"]:
            resultados[(normalizar(f["muestra"]), f["parametro"])] = f
    puntos = {normalizar(r["clave"]): dict(r) for r in p.con.execute("SELECT * FROM puntos")}
    claves_originales = {normalizar(k): k for k in [f["muestra"] for f in p.tabla_resultados()]}

    for t in doc.tablas:
        enc = _encabezado(t.filas)
        cabecera = t.filas[enc[0]] if enc else (t.filas[0] if t.filas else [])
        cols_param = enc[1] if enc else {}
        col_x = _col(cabecera, r"(^|\s)(x|este|e)(\s|$|\()|coordenada x|utm x")
        col_y = _col(cabecera, r"(^|\s)(y|norte|n)(\s|$|\()|coordenada y|utm y")
        col_dict = _col(cabecera, r"cumpl|dictamen|condicion")
        inicio = (enc[0] + 1) if enc else 1
        for fila in t.filas[inicio:]:
            fila_txt = " | ".join(fila)
            celdas_norm = [normalizar(c) for c in fila]
            # Fila de LMP: compara contra el catálogo NOM-138.
            if any(re.match(r"^(lmp|limite maximo)", c) for c in celdas_norm[:3]):
                for j, clave in cols_param.items():
                    citado = _num(fila[j]) if j < len(fila) else None
                    correcto = lmp_aplicable(clave, usos)
                    if citado is not None and _distinto(citado, correcto):
                        h.append(Hallazgo(
                            "automatica", "vacio_regulatorio", "critica", t.ubicacion,
                            f"LMP de {PARAMETROS[clave].nombre} citado: {citado:g} mg/kg. Para el uso de suelo "
                            f"del proyecto la {NORMA}, {PARAMETROS[clave].tabla}, establece {correcto:g} mg/kg.",
                            evidencia=fila_txt, riesgo="Dictamen de cumplimiento erróneo.",
                            recomendacion="Corregir el LMP y reevaluar el cumplimiento de todas las muestras.",
                            referencia=f"{NORMA}, {PARAMETROS[clave].tabla}", evidencia_localizada=True))
                continue
            muestra = next((c for c in celdas_norm if c in claves_originales), None)
            punto_fila = next((c for c in celdas_norm if c in puntos), None)
            if muestra:
                for j, clave in cols_param.items():
                    if j >= len(fila) or not fila[j].strip():
                        continue
                    v = interpretar_valor(fila[j])
                    ref = resultados.get((muestra, clave))
                    if v is None or ref is None:
                        if v is not None and ref is None:
                            h.append(Hallazgo(
                                "automatica", "inconsistencia_laboratorio", "media", t.ubicacion,
                                f"Se reporta {PARAMETROS[clave].nombre} para {claves_originales[muestra]} "
                                "sin resultado de laboratorio cargado en el proyecto.",
                                evidencia=fila_txt, recomendacion="Verificar el dato contra el informe del laboratorio.",
                                evidencia_localizada=True))
                        continue
                    valor, menor = v
                    lab_menor = bool(ref["menor_que"])
                    if menor != lab_menor or (valor is not None and ref["valor"] is not None
                                              and _distinto(valor, ref["valor"])):
                        lab = ("<" if lab_menor else "") + (f"{ref['valor']:g}" if ref["valor"] is not None else "ND")
                        h.append(Hallazgo(
                            "automatica", "inconsistencia_laboratorio", "alta", t.ubicacion,
                            f"{claves_originales[muestra]}, {PARAMETROS[clave].nombre}: el informe reporta "
                            f"{fila[j]} y el laboratorio {lab}.",
                            evidencia=fila_txt,
                            riesgo="Transcripción errónea de resultados; afecta el dictamen de cumplimiento.",
                            recomendacion="Corregir el valor conforme al informe oficial del laboratorio.",
                            evidencia_localizada=True))
                ev = evaluadas.get(claves_originales[muestra])
                if col_dict is not None and col_dict < len(fila) and ev:
                    dice = normalizar(fila[col_dict])
                    afirma_cumple = "cumple" in dice and "no cumple" not in dice
                    if afirma_cumple and ev.estado == EXCEDE:
                        h.append(Hallazgo(
                            "automatica", "contradictorio", "critica", t.ubicacion,
                            f"La tabla dictamina «{fila[col_dict]}» para {claves_originales[muestra]}, pero excede "
                            f"el LMP de: {', '.join(PARAMETROS[x].nombre for x in ev.excedencias)}.",
                            evidencia=fila_txt, riesgo="Conclusión de cumplimiento incorrecta ante la autoridad.",
                            recomendacion="Corregir el dictamen de la muestra y las conclusiones derivadas.",
                            referencia=NORMA, evidencia_localizada=True))
            # Coordenadas
            if col_x is not None and col_y is not None and max(col_x, col_y) < len(fila):
                x, y = _num(fila[col_x]), _num(fila[col_y])
                if x is None or y is None:
                    continue
                if not (100_000 <= x <= 900_000) or not (1_500_000 <= y <= 3_700_000):
                    h.append(Hallazgo(
                        "automatica", "fuera_de_rango", "alta", t.ubicacion,
                        f"Coordenadas UTM fuera de rango para México: X={fila[col_x]}, Y={fila[col_y]} "
                        "(X esperado de 6 dígitos, Y de 7 dígitos).",
                        evidencia=fila_txt, recomendacion="Revisar el orden X/Y, dígitos y zona UTM.",
                        evidencia_localizada=True))
                    continue
                clave_punto = punto_fila or (normalizar(muestra_punto.get(muestra) or "") if muestra else None)
                ref_p = puntos.get(clave_punto or "")
                if ref_p and ref_p["utm_x"] is not None and ref_p["utm_y"] is not None:
                    dx, dy = abs(x - ref_p["utm_x"]), abs(y - ref_p["utm_y"])
                    if max(dx, dy) > 2:
                        h.append(Hallazgo(
                            "automatica", "coordenadas", "alta", t.ubicacion,
                            f"Coordenadas del punto {ref_p['clave']} difieren de las registradas "
                            f"(X {ref_p['utm_x']:.2f}, Y {ref_p['utm_y']:.2f}); diferencia de {max(dx, dy):.1f} m.",
                            evidencia=fila_txt, recomendacion="Unificar coordenadas con la libreta de campo y el plano.",
                            evidencia_localizada=True))
    return h


# --------------------------------------------------------------------------- afirmaciones de cumplimiento
_AFIRMA_CUMPLE = [
    re.compile(r"todas las muestras(?: analizadas)?\s+(?:cumplen|se encuentran por debajo|estan por debajo)", re.I),
    re.compile(r"ninguna(?: de las)? muestras?\s+(?:excede|rebasa|supera)", re.I),
    re.compile(r"no se (?:detectaron|encontraron|registraron|identificaron) concentraciones "
               r"(?:por encima|superiores|que (?:excedan|rebasen|superen))", re.I),
]
_AFIRMA_EXCEDE = re.compile(r"se (?:detectaron|identificaron|registraron|encontraron) (?:concentraciones|valores) "
                            r"(?:por encima|superiores) (?:de|a) (?:los |el )?(?:lmp|limites? maximos?)", re.I)
_RE_USO = re.compile(r"uso de suelo\s+(?:es\s+|de tipo\s+|)(" + "|".join(_USOS_TEXTO) + ")", re.I)


def verificar_afirmaciones(doc: Documento, evaluadas: list[MuestraEvaluada], usos: list[UsoSuelo]) -> list[Hallazgo]:
    h: list[Hallazgo] = []
    excedentes = [m for m in evaluadas if m.estado == EXCEDE]
    for b in doc.bloques:
        if b.tipo == "tabla":
            continue
        t = normalizar(b.texto)
        if excedentes:
            for rx in _AFIRMA_CUMPLE:
                m = rx.search(t)
                if m:
                    h.append(Hallazgo(
                        "automatica", "contradictorio", "critica", b.ubicacion,
                        f"El texto afirma cumplimiento, pero {len(excedentes)} muestra(s) exceden LMP según los "
                        "resultados del laboratorio: " + ", ".join(x.muestra for x in excedentes[:10]) + ".",
                        evidencia=b.texto[:400], riesgo="Conclusión contraria a los resultados analíticos.",
                        recomendacion="Corregir la conclusión e incluir las muestras que exceden y su extensión.",
                        referencia=NORMA, evidencia_localizada=True))
                    break
        elif evaluadas:
            m = _AFIRMA_EXCEDE.search(t)
            if m:
                h.append(Hallazgo(
                    "automatica", "contradictorio", "alta", b.ubicacion,
                    "El texto afirma concentraciones por encima de los LMP, pero ninguna muestra excede "
                    "según los resultados cargados.", evidencia=b.texto[:400],
                    recomendacion="Verificar resultados y conclusión.", evidencia_localizada=True))
        for m in _RE_USO.finditer(t):
            uso = _USOS_TEXTO[m.group(1).lower()]
            if usos and uso not in usos:
                h.append(Hallazgo(
                    "automatica", "inconsistencia_tabla_texto", "alta", b.ubicacion,
                    f"El informe refiere uso de suelo «{m.group(1)}» ({uso.etiqueta}); el proyecto está configurado "
                    f"como {' / '.join(u.etiqueta for u in usos)}. Esto cambia los LMP aplicables.",
                    evidencia=b.texto[:400], recomendacion="Unificar el uso de suelo y verificar los LMP aplicados.",
                    referencia=f"{NORMA}, Tablas 2 y 3", evidencia_localizada=True))
    # Muestras que exceden y no se mencionan en ninguna parte del informe.
    todo = normalizar("\n".join(b.texto for b in doc.bloques))
    for m in excedentes:
        if normalizar(m.muestra) not in todo:
            h.append(Hallazgo(
                "automatica", "insuficiente", "alta", "Resultados",
                f"La muestra {m.muestra} ({m.zona or 'sin zona'}) excede el LMP de "
                f"{', '.join(PARAMETROS[x].nombre for x in m.excedencias)} y no se menciona en el informe.",
                riesgo="Omisión de una excedencia en la delimitación del área afectada.",
                recomendacion="Incluir la muestra en las tablas de resultados y en la delimitación de la pluma."))
    return h


# --------------------------------------------------------------------------- fechas
def _fechas(doc: Documento) -> list[tuple[Bloque, str, date | None]]:
    out: list[tuple[Bloque, str, date | None]] = []
    for b in doc.bloques:
        for m in _RE_FECHA_NUM.finditer(b.texto):
            out.append((b, m.group(0), _fecha(int(m.group(3)), int(m.group(2)), int(m.group(1)))))
        for m in _RE_FECHA_ISO.finditer(b.texto):
            out.append((b, m.group(0), _fecha(int(m.group(1)), int(m.group(2)), int(m.group(3)))))
        for m in _RE_FECHA_TEXTO.finditer(normalizar(b.texto)):
            out.append((b, m.group(0), _fecha(int(m.group(3)), _MESES[m.group(2).lower()], int(m.group(1)))))
    return out


def _fecha(a: int, m: int, d: int) -> date | None:
    try:
        return date(a, m, d)
    except ValueError:
        return None


def _fecha_texto(valor: str | None) -> date | None:
    if not valor:
        return None
    v = str(valor).strip()
    if m := _RE_FECHA_ISO.search(v):
        return _fecha(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if m := _RE_FECHA_NUM.search(v):
        return _fecha(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def verificar_fechas(doc: Documento, p: Proyecto, hoy: date | None = None) -> list[Hallazgo]:
    hoy = hoy or date.today()
    h: list[Hallazgo] = []
    encontradas = _fechas(doc)
    for b, texto, f in encontradas:
        if f is None:
            h.append(Hallazgo(
                "automatica", "fechas", "media", b.ubicacion, f"Fecha inválida: «{texto}».",
                evidencia=texto, recomendacion="Corregir la fecha.", evidencia_localizada=True))
        elif f > hoy and not re.search(r"programa|cronograma|saneamiento|remediacion", normalizar(b.seccion)):
            h.append(Hallazgo(
                "automatica", "fechas", "media", b.ubicacion, f"Fecha posterior a la fecha de revisión: «{texto}».",
                evidencia=texto, recomendacion="Verificar la fecha; solo el programa de actividades admite fechas futuras.",
                evidencia_localizada=True))
    muestreo = {d for f in p.con.execute("SELECT DISTINCT fecha_muestreo FROM muestras")
                if (d := _fecha_texto(f["fecha_muestreo"]))}
    citadas = {f for _, _, f in encontradas if f}
    faltan = sorted(muestreo - citadas)
    if faltan:
        h.append(Hallazgo(
            "automatica", "fechas", "media", "Metodología de muestreo",
            "Las fechas de muestreo registradas por el laboratorio no aparecen en el informe: "
            + ", ".join(d.strftime("%d/%m/%Y") for d in faltan) + ".",
            recomendacion="Indicar las fechas de muestreo y verificar que coincidan con las cadenas de custodia."))
    return h


# --------------------------------------------------------------------------- información pendiente
_RE_PENDIENTE = re.compile(r"\[(?:COMPLETAR|DATO PENDIENTE)[^\]]*\]")


def verificar_pendientes(doc: Documento) -> list[Hallazgo]:
    """Marcadores de información por completar: uno crítico global y uno por sección afectada."""
    encontrados = [(b, m.group()) for b in doc.bloques for m in _RE_PENDIENTE.finditer(b.texto)]
    if not encontrados:
        return []
    por_seccion: dict[str, list[tuple[Bloque, str]]] = {}
    for b, m in encontrados:
        por_seccion.setdefault(b.seccion, []).append((b, m))
    h = [Hallazgo(
        "automatica", "insuficiente", "critica", "Documento completo",
        f"El documento contiene {len(encontrados)} marcador(es) de información por completar en "
        f"{len(por_seccion)} sección(es); no está listo para ingreso.",
        evidencia=encontrados[0][1], riesgo="Prevención por información incompleta.",
        recomendacion="Completar todos los marcadores [COMPLETAR…]/[DATO PENDIENTE…] antes del ingreso.",
        evidencia_localizada=True)]
    for seccion, items in por_seccion.items():
        h.append(Hallazgo(
            "automatica", "insuficiente", "media", seccion,
            f"{len(items)} dato(s) por completar en «{seccion}».", evidencia=items[0][1],
            recomendacion="Completar con la información de campo o documental correspondiente.",
            evidencia_localizada=True))
    return h


# --------------------------------------------------------------------------- orquestación
def verificar(doc: Documento, p: Proyecto, hoy: date | None = None) -> list[Hallazgo]:
    usos = p.usos_suelo()
    filas = p.tabla_resultados()
    evaluadas = evaluar(filas, usos, p.ficha().get("producto")) if usos and any(f["parametro"] for f in filas) else []
    conteo = p.conteos()
    h = verificar_normativa(doc)
    h += verificar_estructura(doc, any(m.estado == EXCEDE for m in evaluadas))
    h += verificar_conteos(doc, conteo["muestras"], conteo["puntos"])
    if usos:
        h += verificar_tablas(doc, p, usos, {m.muestra: m for m in evaluadas})
    h += verificar_afirmaciones(doc, evaluadas, usos)
    h += verificar_fechas(doc, p, hoy)
    h += verificar_pendientes(doc)
    return h
