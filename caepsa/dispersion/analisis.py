"""Módulo 6 — Análisis determinista de la dispersión de hidrocarburos.

Todo lo calculado aquí sale de los resultados del laboratorio, las coordenadas registradas y los datos del
medio físico con fuente. La matriz de susceptibilidad es un tamizaje cualitativo con reglas explícitas
(constantes al inicio del módulo, editables por CAEPSA); no sustituye una modelación numérica.
"""
from __future__ import annotations

import math
import re
from typing import Any

from ..normativa.evaluacion import EXCEDE, evaluar
from ..normativa.nom138 import BTEX, NORMA, PARAMETROS
from ..proyectos import Proyecto
from . import medio_fisico as mf

# ------------------------------------------------------------------ criterios de tamizaje (editables)
TEXTURA_INFILTRACION = {
    "arena": "alta", "arena franca": "alta", "franco arenoso": "alta",
    "franco": "media", "franco limoso": "media", "limo": "media", "franco arcillo arenoso": "media",
    "franco arcilloso": "baja", "franco arcillo limoso": "baja", "arcilla arenosa": "baja",
    "arcilla limosa": "baja", "arcilla": "baja",
}
K_ALTA_CM_S, K_BAJA_CM_S = 1e-3, 1e-5          # conductividad hidráulica
FREATICO_ALTA_M, FREATICO_BAJA_M = 5.0, 15.0   # profundidad al nivel freático
PENDIENTE_ALTA_PCT, PENDIENTE_BAJA_PCT = 8.0, 2.0
PRECIPITACION_ALTA_MM = 1000.0
CUERPO_AGUA_ALTA_M, CUERPO_AGUA_BAJA_M = 100.0, 500.0
MOVILIDAD_FRACCION = {"HFL": "alta", "HFM": "media", "HFP": "baja"}
CRITERIO = "Criterio de tamizaje cualitativo de CAEPSA (no normativo); no sustituye modelación numérica."

NIVELES = ("baja", "media", "alta")


def cientifica(x: float) -> str:
    """1e-05 → «1×10⁻⁵» para texto de informe."""
    exp = math.floor(math.log10(x))
    mant = x / 10 ** exp
    sup = str(exp).translate(str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹"))
    return f"{mant:g}×10{sup}"


def _subir(nivel: str, pasos: int = 1) -> str:
    return NIVELES[max(0, min(2, NIVELES.index(nivel) + pasos))]


def rumbo(azimut: float) -> str:
    return mf.RUMBOS[int(((azimut % 360) + 22.5) // 45) % 8]


def azimut(x0: float, y0: float, x1: float, y1: float) -> float:
    return math.degrees(math.atan2(x1 - x0, y1 - y0)) % 360


def diferencia_angular(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def profundidad(texto: Any) -> float | None:
    """'0.30', '0.0-0.3 m', '1.00' → profundidad máxima del intervalo, en m."""
    numeros = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", str(texto or "").replace(",", "."))]
    return max(numeros) if numeros else None


def envolvente_convexa(puntos: list[tuple[float, float]]) -> list[tuple[float, float]]:
    pts = sorted(set(puntos))
    if len(pts) < 3:
        return pts

    def cruz(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    inferior: list[tuple[float, float]] = []
    for p in pts:
        while len(inferior) >= 2 and cruz(inferior[-2], inferior[-1], p) <= 0:
            inferior.pop()
        inferior.append(p)
    superior: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(superior) >= 2 and cruz(superior[-2], superior[-1], p) <= 0:
            superior.pop()
        superior.append(p)
    return inferior[:-1] + superior[:-1]


def area_poligono(vertices: list[tuple[float, float]]) -> float:
    if len(vertices) < 3:
        return 0.0
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(vertices, vertices[1:] + vertices[:1]))) / 2


# ------------------------------------------------------------------ análisis
def analizar(p: Proyecto) -> dict[str, Any]:
    datos = mf.leer(p)
    v = lambda k: mf.valor(datos, k)  # noqa: E731  (solo valores con fuente)
    usos = p.usos_suelo()
    filas = p.tabla_resultados()
    pendientes: list[str] = []
    if not usos or not any(f["parametro"] for f in filas):
        return {"disponible": False, "motivo": "Se requieren resultados de laboratorio y uso de suelo del proyecto",
                "pendientes": ["Cargar resultados de laboratorio (Módulo 2) y definir uso de suelo (Módulo 1)"]}

    evaluadas = evaluar(filas, usos, p.ficha().get("producto"))
    # Indicador: la fracción (o, en su defecto, el parámetro) con mayor relación valor/LMP.
    proporciones: dict[str, float] = {}
    for m in evaluadas:
        for r in m.resultados:
            if r.proporcion is not None:
                proporciones[r.parametro] = max(proporciones.get(r.parametro, 0.0), r.proporcion)
    fracciones = {k: x for k, x in proporciones.items() if k in MOVILIDAD_FRACCION}
    indicador = max(fracciones or proporciones, key=(fracciones or proporciones).get) if proporciones else None

    coords = {r["clave"]: dict(r) for r in p.con.execute("SELECT clave, zona, utm_x, utm_y FROM puntos")}
    por_punto: dict[str, list[Any]] = {}
    for m in evaluadas:
        por_punto.setdefault(m.punto or m.muestra, []).append(m)

    puntos: list[dict[str, Any]] = []
    for clave, muestras in sorted(por_punto.items()):
        c = coords.get(clave, {})
        profs = [(profundidad(m.datos.get("profundidad_m")), m) for m in muestras]
        con_prof = [(d, m) for d, m in profs if d is not None]
        prof_max = max((d for d, _ in con_prof), default=None)
        exced = [(d, m) for d, m in con_prof if m.estado == EXCEDE]
        prof_exc = max((d for d, _ in exced), default=None)
        prof_mas_honda = [m for d, m in con_prof if d == prof_max]
        ind = [r for m in muestras for r in m.resultados if r.parametro == indicador and r.proporcion is not None]
        puntos.append({
            "punto": clave, "zona": c.get("zona") or (muestras[0].zona if muestras else None),
            "x": c.get("utm_x"), "y": c.get("utm_y"), "muestras": len(muestras),
            "excede": any(m.estado == EXCEDE for m in muestras),
            "parametros_excedidos": sorted({x for m in muestras for x in m.excedencias}, key=list(PARAMETROS).index),
            "prof_max_muestreada_m": prof_max, "prof_max_excedencia_m": prof_exc,
            "vertical_abierta": bool(prof_mas_honda) and any(m.estado == EXCEDE for m in prof_mas_honda),
            "indicador_max": max((r.valor for r in ind), default=None),
            "indicador_proporcion_max": max((r.proporcion for r in ind), default=None),
        })

    con_coord = [x for x in puntos if x["x"] is not None and x["y"] is not None]
    sin_coord = [x["punto"] for x in puntos if x["x"] is None or x["y"] is None]
    if sin_coord:
        pendientes.append(f"Coordenadas UTM faltantes en {len(sin_coord)} punto(s): {', '.join(sin_coord[:10])}")
    excedentes = [x for x in con_coord if x["excede"]]

    # Origen del derrame
    ox, oy = v("origen_x"), v("origen_y")
    if ox is not None and oy is not None:
        origen = {"x": ox, "y": oy, "tipo": "documentado", "fuente": datos["origen_x"]["fuente"]}
    elif excedentes:
        mayor = max(excedentes, key=lambda x: x["indicador_proporcion_max"] or 0)
        origen = {"x": mayor["x"], "y": mayor["y"], "tipo": "punto de mayor concentración", "punto": mayor["punto"]}
        pendientes.append("Origen del derrame sin coordenadas documentadas; se usa el punto de mayor concentración")
    else:
        origen = None

    espacial: dict[str, Any] = {"puntos_con_excedencia": len(excedentes), "puntos_evaluados": len(puntos)}
    if excedentes and origen:
        dist = [math.hypot(x["x"] - origen["x"], x["y"] - origen["y"]) for x in excedentes]
        espacial["extension_max_m"] = round(max(dist), 1)
        pesos = [(x["indicador_proporcion_max"] or 1.0) for x in excedentes]
        cx = sum(x["x"] * w for x, w in zip(excedentes, pesos)) / sum(pesos)
        cy = sum(x["y"] * w for x, w in zip(excedentes, pesos)) / sum(pesos)
        if math.hypot(cx - origen["x"], cy - origen["y"]) > 1.0:
            az = azimut(origen["x"], origen["y"], cx, cy)
            espacial["direccion_dispersion"] = {"azimut": round(az), "rumbo": rumbo(az)}
            dp = v("direccion_pendiente")
            if dp:
                dif = diferencia_angular(az, mf.AZIMUT[dp])
                espacial["coincidencia_pendiente"] = {
                    "direccion_pendiente": dp, "diferencia_grados": round(dif),
                    "valoracion": "coincide" if dif <= 45 else "parcial" if dif <= 90 else "no coincide"}
        envolvente = envolvente_convexa([(x["x"], x["y"]) for x in excedentes])
        area = area_poligono(envolvente)
        if area > 0:
            espacial["area_afectada_m2"] = round(area, 1)
            espacial["envolvente"] = [[round(a, 2), round(b, 2)] for a, b in envolvente]
        else:
            pendientes.append("Área afectada no estimable: se requieren al menos 3 puntos con excedencia no alineados")

    # Delimitación
    periferia_exc = [x for x in excedentes if "periferia" in (x["zona"] or "").lower()]
    delim_h = {"cerrada": not periferia_exc and len(excedentes) < len(con_coord),
               "motivo": "" if excedentes else "Sin excedencias"}
    if periferia_exc:
        rumbos = sorted({rumbo(azimut(origen["x"], origen["y"], x["x"], x["y"])) for x in periferia_exc}) if origen \
            else []
        delim_h["motivo"] = (f"Excedencias en puntos de la periferia: {', '.join(x['punto'] for x in periferia_exc)}"
                             + (f" (hacia {', '.join(rumbos)})" if rumbos else ""))
    elif excedentes and len(excedentes) == len(con_coord):
        delim_h["motivo"] = "Todos los puntos con coordenadas exceden: no hay puntos que delimiten la afectación"
    abiertas_v = [x for x in puntos if x["vertical_abierta"]]
    delim_v = {"cerrada": not abiertas_v,
               "motivo": ("Excedencia en la muestra más profunda de: " + ", ".join(
                   f"{x['punto']} ({x['prof_max_muestreada_m']:g} m)" for x in abiertas_v)) if abiertas_v else ""}
    if not delim_h["cerrada"] and excedentes:
        pendientes.append("Delimitación horizontal abierta: " + delim_h["motivo"])
    if abiertas_v:
        pendientes.append("Delimitación vertical abierta: " + delim_v["motivo"])

    profs_exc = [x["prof_max_excedencia_m"] for x in excedentes if x["prof_max_excedencia_m"] is not None]
    if "area_afectada_m2" in espacial and profs_exc:
        espacial["prof_max_afectacion_m"] = max(profs_exc)
        espacial["prof_media_afectacion_m"] = round(sum(profs_exc) / len(profs_exc), 2)
        espacial["volumen_estimado_m3"] = {
            "central": round(espacial["area_afectada_m2"] * espacial["prof_media_afectacion_m"], 1),
            "conservador": round(espacial["area_afectada_m2"] * espacial["prof_max_afectacion_m"], 1),
            "metodo": "área de la envolvente de puntos con excedencia × profundidad media / máxima de excedencia",
        }

    matriz, transito = _matriz(datos, v, indicador, evaluadas, espacial, delim_v)
    receptores = _receptores(v)
    falt = mf.faltantes(datos)
    pendientes += [f"Dato del medio físico sin capturar: {c.etiqueta}" for c in falt["sin_valor"]]
    pendientes += [f"Dato sin fuente documentada (no se usa): {c.etiqueta}" for c in falt["sin_fuente"]]

    return {
        "disponible": True, "norma": NORMA,
        "uso_suelo": [u.etiqueta for u in usos], "producto": p.ficha().get("producto"),
        "indicador": {"clave": indicador, "nombre": PARAMETROS[indicador].nombre} if indicador else None,
        "origen": origen, "puntos": puntos, "espacial": espacial,
        "delimitacion": {"horizontal": delim_h, "vertical": delim_v},
        "matriz": matriz, "transito_vertical": transito, "receptores": receptores,
        "medio_fisico": {k: {"etiqueta": mf.POR_CLAVE[k].etiqueta, "valor": d["valor"],
                             "unidad": mf.POR_CLAVE[k].unidad, "fuente": d["fuente"]}
                         for k, d in datos.items() if k in mf.POR_CLAVE and d["valor"] is not None and d["fuente"]},
        "pendientes": pendientes, "criterio_tamizaje": CRITERIO,
    }


def _matriz(datos: dict[str, Any], v: Any, indicador: str | None, evaluadas: list[Any], espacial: dict[str, Any],
            delim_v: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, Any] | None]:
    m: list[dict[str, str]] = []

    # 1. Infiltración / lixiviación vertical
    k, textura, fract = v("conductividad_hidraulica_cm_s"), v("textura"), v("fracturamiento")
    if k is not None:
        inf = "alta" if k > K_ALTA_CM_S else "baja" if k < K_BAJA_CM_S else "media"
        just = (f"K = {cientifica(k)} cm/s; criterio: alta > {cientifica(K_ALTA_CM_S)} cm/s, "
                f"baja < {cientifica(K_BAJA_CM_S)} cm/s")
    elif textura:
        inf, just = TEXTURA_INFILTRACION[textura], f"textura {textura}"
    else:
        inf, just = "indeterminado", "sin textura ni conductividad hidráulica documentadas"
    if inf != "indeterminado" and fract == "intenso":
        inf, just = _subir(inf), just + "; se eleva un nivel por fracturamiento intenso"
    m.append({"factor": "Infiltración y lixiviación vertical", "nivel": inf, "justificacion": just})

    # 2. Vulnerabilidad del agua subterránea
    nf = v("profundidad_nivel_freatico_m")
    if nf is None:
        vul, just = "indeterminado", "profundidad al nivel freático no documentada"
    else:
        vul = "alta" if nf < FREATICO_ALTA_M else "baja" if nf > FREATICO_BAJA_M else "media"
        just = f"nivel freático a {nf:g} m; criterio: alta < {FREATICO_ALTA_M:g} m, baja > {FREATICO_BAJA_M:g} m"
        if inf == "alta":
            vul, just = _subir(vul), just + "; infiltración alta"
        elif inf == "baja":
            vul, just = _subir(vul, -1), just + "; infiltración baja"
        prof_exc = espacial.get("prof_max_afectacion_m")
        if prof_exc is not None and prof_exc >= nf - 1:
            vul, just = "alta", just + f"; la afectación alcanza {prof_exc:g} m, a ≤ 1 m del nivel freático"
        elif not delim_v["cerrada"]:
            just += "; delimitación vertical abierta"
    m.append({"factor": "Vulnerabilidad del agua subterránea", "nivel": vul, "justificacion": just})

    # 3. Escurrimiento superficial
    pend, precip = v("pendiente_pct"), v("precipitacion_anual_mm")
    if pend is None:
        esc, just = "indeterminado", "pendiente no documentada"
    else:
        esc = "alta" if pend > PENDIENTE_ALTA_PCT else "baja" if pend < PENDIENTE_BAJA_PCT else "media"
        just = f"pendiente de {pend:g} %; criterio: alta > {PENDIENTE_ALTA_PCT:g} %, baja < {PENDIENTE_BAJA_PCT:g} %"
        if precip is not None and precip >= PRECIPITACION_ALTA_MM:
            esc, just = _subir(esc), just + f"; se eleva un nivel por precipitación de {precip:g} mm/año " \
                f"(≥ {PRECIPITACION_ALTA_MM:g})"
    m.append({"factor": "Arrastre por escurrimiento superficial", "nivel": esc, "justificacion": just})

    # 4. Cuerpos de agua superficiales
    tipo, dist = v("tipo_cuerpo_agua"), v("distancia_cuerpo_agua_m")
    if tipo == "ninguno identificado":
        sup, just = "baja", "no se identificó cuerpo de agua cercano"
    elif dist is None:
        sup, just = "indeterminado", "distancia al cuerpo de agua no documentada"
    else:
        sup = "alta" if dist < CUERPO_AGUA_ALTA_M else "baja" if dist > CUERPO_AGUA_BAJA_M else "media"
        just = (f"{tipo or 'cuerpo de agua'} a {dist:g} m; criterio: alta < {CUERPO_AGUA_ALTA_M:g} m, "
                f"baja > {CUERPO_AGUA_BAJA_M:g} m")
        dc, dp = v("direccion_cuerpo_agua"), v("direccion_pendiente")
        if dc and dp and diferencia_angular(mf.AZIMUT[dc], mf.AZIMUT[dp]) <= 45:
            sup, just = _subir(sup), just + f"; se eleva un nivel por ubicarse pendiente abajo ({dc})"
    m.append({"factor": "Afectación de cuerpos de agua superficiales", "nivel": sup, "justificacion": just})

    # 5. Movilidad del contaminante
    btex_exc = sorted({x for e in evaluadas for x in e.excedencias if x in BTEX})
    if indicador in MOVILIDAD_FRACCION:
        mov = MOVILIDAD_FRACCION[indicador]
        just = f"fracción dominante: {PARAMETROS[indicador].nombre.lower()}"
    else:
        mov, just = "indeterminado", "sin fracciones de hidrocarburos evaluadas"
    if btex_exc:
        mov, just = "alta", just + "; excedencias de " + ", ".join(PARAMETROS[x].nombre for x in btex_exc)
    m.append({"factor": "Movilidad del contaminante", "nivel": mov, "justificacion": just})

    transito = None
    n = v("porosidad_efectiva")
    if k and n and nf is not None:
        espesor = max(nf - (espacial.get("prof_max_afectacion_m") or 0.0), 0.0)
        vel = k / n  # cm/s
        transito = {
            "espesor_no_saturado_m": round(espesor, 2), "velocidad_cm_s": vel,
            "dias": round(espesor * 100 / vel / 86400, 1),
            "supuesto": "Flujo vertical saturado con gradiente unitario (estimación conservadora: sobrestima la "
                        "velocidad real en zona no saturada)."}
    return m, transito


def _receptores(v: Any) -> list[dict[str, Any]]:
    r = []
    if v("cobertura_vegetal"):
        r.append({"receptor": "Cobertura vegetal / cultivos", "descripcion": v("cobertura_vegetal")})
    if v("uso_actual"):
        r.append({"receptor": "Uso actual del predio", "descripcion": v("uso_actual")})
    if v("tipo_cuerpo_agua") and v("tipo_cuerpo_agua") != "ninguno identificado":
        r.append({"receptor": "Cuerpo de agua superficial",
                  "descripcion": " ".join(str(x) for x in (v("tipo_cuerpo_agua"), v("cuerpo_agua")) if x),
                  "distancia_m": v("distancia_cuerpo_agua_m"), "direccion": v("direccion_cuerpo_agua")})
    if v("distancia_pozo_m") is not None:
        r.append({"receptor": "Pozo de agua", "descripcion": v("acuifero") or "", "distancia_m": v("distancia_pozo_m")})
    if v("profundidad_nivel_freatico_m") is not None:
        r.append({"receptor": "Agua subterránea", "descripcion": v("acuifero") or "",
                  "profundidad_m": v("profundidad_nivel_freatico_m")})
    return r
