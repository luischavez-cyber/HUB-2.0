"""Tablero del proyecto: avance por módulo y alertas pendientes."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .dispersion import capitulo as capitulo5
from .dispersion import medio_fisico as mf
from .dispersion.analisis import analizar as analizar_dispersion
from .fotografia.clasificador import CATEGORIAS
from .fotografia.registro import diagnostico
from .normativa.evaluacion import EXCEDE, INDETERMINADO, evaluar
from .normativa.nom138 import PARAMETROS
from .proyectos import CAMPOS_FICHA, Proyecto, campos_faltantes
from .revision.registro import hallazgos_de, listar_revisiones

MODULOS = (
    (1, "Gestión de Proyectos"),
    (2, "Extracción de Resultados de Laboratorio"),
    (3, "Evaluación Normativa NOM-138"),
    (4, "Gestión Fotográfica"),
    (5, "Revisión Técnica Ambiental"),
    (6, "Análisis de Dispersión"),
    (7, "Generación de Informes"),
)
DISPONIBLES = {1, 2, 3, 4, 5, 6, 7}


@dataclass
class Alerta:
    nivel: str  # "alta" | "media" | "info"
    modulo: int
    mensaje: str


def _entero(v: object) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def estado(p: Proyecto) -> tuple[dict[int, float], list[Alerta]]:
    ficha = p.ficha()
    alertas: list[Alerta] = []
    avance: dict[int, float] = {n: 0.0 for n, _ in MODULOS}

    # Módulo 1
    faltan = campos_faltantes(ficha)
    requeridos = [c for c in CAMPOS_FICHA if c.requerido]
    avance[1] = (len(requeridos) - len(faltan)) / len(requeridos)
    if faltan:
        alertas.append(Alerta("media", 1, "Ficha incompleta: " + ", ".join(c.etiqueta for c in faltan)))

    # Módulo 2
    filas = p.tabla_resultados()
    conteo = p.conteos()
    esperadas = _entero(ficha.get("muestras_esperadas"))
    puntos_esp = _entero(ficha.get("puntos_esperados"))
    if not p.documentos("laboratorio"):
        alertas.append(Alerta("media", 2, "No se ha cargado el PDF oficial del laboratorio"))
    if conteo["muestras"]:
        sin_coord = {f["punto"] or f["muestra"] for f in filas if f["utm_x"] is None or f["utm_y"] is None}
        sin_prof = {f["muestra"] for f in filas if not f["profundidad_m"]}
        sin_zona = {f["muestra"] for f in filas if not f["zona"]}
        completas = conteo["muestras"] - len({f["muestra"] for f in filas
                                               if f["utm_x"] is None or not f["profundidad_m"] or not f["zona"]})
        base = max(esperadas or conteo["muestras"], conteo["muestras"])
        avance[2] = completas / base
        if sin_coord:
            alertas.append(Alerta("alta", 2, f"{len(sin_coord)} punto(s)/muestra(s) sin coordenadas UTM"))
        if sin_prof:
            alertas.append(Alerta("media", 2, f"{len(sin_prof)} muestra(s) sin profundidad"))
        if sin_zona:
            alertas.append(Alerta("media", 2, f"{len(sin_zona)} muestra(s) sin zona asignada"))
    if esperadas and conteo["muestras"] != esperadas:
        alertas.append(Alerta("alta", 2, f"Muestras registradas ({conteo['muestras']}) ≠ esperadas ({esperadas})"))
    if puntos_esp and conteo["puntos"] != puntos_esp:
        alertas.append(Alerta("alta", 2, f"Puntos registrados ({conteo['puntos']}) ≠ esperados ({puntos_esp})"))

    # Módulo 3
    usos = p.usos_suelo()
    if not usos:
        alertas.append(Alerta("alta", 3, "Sin uso de suelo definido: no es posible seleccionar LMP"))
    elif conteo["resultados"]:
        evaluadas = evaluar(filas, usos, ficha.get("producto"))
        avance[3] = sum(1 for m in evaluadas if not m.faltantes) / len(evaluadas)
        exc = [m for m in evaluadas if m.estado == EXCEDE]
        if exc:
            params = sorted({x for m in exc for x in m.excedencias}, key=list(PARAMETROS).index)
            alertas.append(Alerta("alta", 3, f"{len(exc)} muestra(s) exceden LMP "
                                             f"({', '.join(PARAMETROS[x].nombre for x in params)})"))
        indet = [m for m in evaluadas if m.estado == INDETERMINADO]
        if indet:
            alertas.append(Alerta("media", 3, f"{len(indet)} muestra(s) con dictamen indeterminado "
                                              "(parámetros de Tabla 1 faltantes o LD > LMP)"))
    # Módulo 4
    d = diagnostico(p)
    if d["total"]:
        incluidas = sum(d["por_categoria"].values()) + len(d["sin_clasificar"])
        clasificadas = incluidas - len(d["sin_clasificar"])
        revisadas = clasificadas - len(d["sin_revisar"])
        avance[4] = (clasificadas + revisadas) / (2 * incluidas) if incluidas else 0.0
        if d["sin_clasificar"]:
            alertas.append(Alerta("media", 4, f"{len(d['sin_clasificar'])} fotografía(s) sin clasificar o sin pie"))
        if d["sin_revisar"]:
            alertas.append(Alerta("media", 4, f"{len(d['sin_revisar'])} fotografía(s) clasificadas por IA "
                                              "pendientes de revisión"))
        if d["pies_largos"]:
            alertas.append(Alerta("media", 4, f"{len(d['pies_largos'])} pie(s) de foto con más de 15 palabras"))
        faltan = [CATEGORIAS[c][0] for c in ("reconocimiento", "muestreo", "laboratorio", "cierre")
                  if not d["por_categoria"][c]]
        if faltan:
            alertas.append(Alerta("info", 4, "Sin evidencia fotográfica de: " + ", ".join(faltan)))
    else:
        alertas.append(Alerta("media", 4, "No se han cargado fotografías del proyecto"))

    # Módulo 5
    revisiones = listar_revisiones(p)
    if revisiones:
        ultima = revisiones[0]
        avance[5] = ultima["ict_vigente"] / 100
        abiertos = [h for h in hallazgos_de(p, ultima["id"]) if h.estado == "abierto"]
        criticos = sum(1 for h in abiertos if h.criticidad == "critica")
        if criticos:
            alertas.append(Alerta("alta", 5, f"{criticos} hallazgo(s) crítico(s) abiertos en la última revisión "
                                             f"({ultima['documento']}, ICT {ultima['ict_vigente']:.0f})"))
        elif abiertos:
            alertas.append(Alerta("media", 5, f"{len(abiertos)} hallazgo(s) abiertos en la última revisión "
                                              f"(ICT {ultima['ict_vigente']:.0f})"))
    elif p.documentos("borrador"):
        alertas.append(Alerta("media", 5, "Hay borradores cargados sin revisión técnica"))

    # Módulo 6
    datos_mf = mf.leer(p)
    requeridos_mf = [c for c in mf.CAMPOS if c.requerido]
    completos = sum(1 for c in requeridos_mf if mf.valor(datos_mf, c.clave) is not None)
    capitulos = capitulo5.listar(p)
    avance[6] = 0.6 * completos / len(requeridos_mf) + (0.4 if capitulos else 0.0)
    if completos < len(requeridos_mf):
        alertas.append(Alerta("media", 6, f"Medio físico: {len(requeridos_mf) - completos} dato(s) requerido(s) "
                                          "sin valor o sin fuente documentada"))
    if conteo["resultados"] and usos:
        a = analizar_dispersion(p)
        for eje in ("horizontal", "vertical"):
            d = a.get("delimitacion", {}).get(eje)
            if d and not d["cerrada"] and a["espacial"]["puntos_con_excedencia"]:
                alertas.append(Alerta("alta", 6, f"Delimitación {eje} abierta: {d['motivo']}"))
    if capitulos and capitulos[0]["cifras_no_respaldadas"]:
        alertas.append(Alerta("media", 6, f"Capítulo 5: {len(capitulos[0]['cifras_no_respaldadas'])} cifra(s) sin "
                                          "respaldo en los datos, resaltadas para revisión"))

    # Módulo 7
    ultimo = ultimo_informe(p)
    if ultimo:
        revs = [r for r in listar_revisiones(p) if r["documento_id"] == ultimo["documento_id"]]
        avance[7] = revs[0]["ict_vigente"] / 100 if revs else 0.5
        if ultimo["pendientes"]:
            alertas.append(Alerta("media", 7, f"{ultimo['nombre']}: {ultimo['pendientes']} dato(s) por completar"))
    elif conteo["resultados"]:
        alertas.append(Alerta("info", 7, "Informe de Caracterización aún no generado"))

    for n, nombre in MODULOS:
        if n not in DISPONIBLES:
            alertas.append(Alerta("info", n, f"{nombre}: módulo programado para una etapa posterior"))
    return avance, alertas


def ultimo_informe(p: Proyecto) -> dict[str, Any] | None:
    """Último informe generado (Módulo 7), según la bitácora."""
    f = p.con.execute("SELECT referencia, despues FROM bitacora WHERE entidad='informe' AND accion='generar' "
                      "ORDER BY id DESC LIMIT 1").fetchone()
    if not f:
        return None
    d = json.loads(f["despues"])
    return {"nombre": f["referencia"], "documento_id": d["documento_id"], "pendientes": d["pendientes"]}
