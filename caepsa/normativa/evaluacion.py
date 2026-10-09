"""Módulo 3 — Evaluación normativa contra la NOM-138-SEMARNAT/SSA1-2012."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .nom138 import (
    NORMA,
    PARAMETROS,
    REFERENCIAS,
    UsoSuelo,
    lmp_aplicable,
    parametros_requeridos,
)

CUMPLE = "Cumple"
EXCEDE = "Excede"
NO_DETECTADO = "No detectado"
INDETERMINADO = "Indeterminado"  # <LD con LD superior al LMP: no demuestra cumplimiento
SIN_DATO = "Sin dato"
NO_NORMADO = "No normado"

_UNIDADES_VALIDAS = re.compile(r"^\s*mg\s*/\s*kg", re.I)


@dataclass
class ResultadoEvaluado:
    muestra: str
    punto: str | None
    zona: str | None
    parametro: str
    valor: float | None
    menor_que: bool
    limite_deteccion: float | None
    lmp: float | None
    estado: str
    proporcion: float | None  # valor / LMP
    referencia: str
    observaciones: list[str] = field(default_factory=list)
    datos: dict[str, Any] = field(default_factory=dict)


@dataclass
class MuestraEvaluada:
    muestra: str
    punto: str | None
    zona: str | None
    estado: str
    excedencias: list[str]
    faltantes: list[str]
    resultados: list[ResultadoEvaluado]
    datos: dict[str, Any]


def evaluar_resultado(fila: dict[str, Any], usos: list[UsoSuelo]) -> ResultadoEvaluado:
    clave = fila.get("parametro")
    valor = fila.get("valor")
    menor_que = bool(fila.get("menor_que"))
    ld = fila.get("limite_deteccion")
    obs: list[str] = []

    if clave not in PARAMETROS:
        return ResultadoEvaluado(fila.get("muestra", ""), fila.get("punto"), fila.get("zona"), str(clave),
                                 valor, menor_que, ld, None, NO_NORMADO, None, NORMA,
                                 ["Parámetro sin LMP en la NOM-138"], fila)

    p = PARAMETROS[clave]
    lmp = lmp_aplicable(clave, usos)
    ref = f"{NORMA}, {p.tabla}"
    if len(set(usos)) > 1:
        ref += f"; {REFERENCIAS['uso_mixto']}"

    unidad = fila.get("unidad")
    if unidad and not _UNIDADES_VALIDAS.match(str(unidad)):
        obs.append(f"Unidad reportada '{unidad}' distinta de mg/kg base seca")

    if menor_que:
        umbral = valor if valor is not None else ld
        if umbral is None:
            estado, prop = NO_DETECTADO, None
            obs.append("Reportado como no detectado sin límite de detección")
        elif umbral > lmp:
            estado, prop = INDETERMINADO, None
            obs.append(f"Límite de detección ({umbral:g}) superior al LMP ({lmp:g}); no demuestra cumplimiento")
        else:
            estado, prop = NO_DETECTADO, None
    elif valor is None:
        estado, prop = SIN_DATO, None
    else:
        prop = valor / lmp
        # El LMP es el máximo permisible: un valor igual al LMP cumple.
        estado = EXCEDE if valor > lmp else CUMPLE

    return ResultadoEvaluado(fila.get("muestra", ""), fila.get("punto"), fila.get("zona"), clave, valor,
                             menor_que, ld, lmp, estado, prop, ref, obs, fila)


def evaluar(filas: Iterable[dict[str, Any]], usos: list[UsoSuelo], producto: str | None) -> list[MuestraEvaluada]:
    """Evalúa todas las muestras. ``filas`` es la vista de ``Proyecto.tabla_resultados``."""
    if not usos:
        raise ValueError("El proyecto no tiene uso de suelo definido; requerido para elegir el LMP (Tablas 2 y 3)")
    requeridos = parametros_requeridos(producto)
    por_muestra: dict[str, list[dict[str, Any]]] = {}
    for f in filas:
        por_muestra.setdefault(f["muestra"], []).append(f)

    salida: list[MuestraEvaluada] = []
    for muestra, grupo in por_muestra.items():
        base = grupo[0]
        evaluados = [evaluar_resultado(f, usos) for f in grupo if f.get("parametro")]
        presentes = {r.parametro for r in evaluados if r.estado != SIN_DATO}
        faltantes = [c for c in requeridos if c not in presentes]
        estados = {r.estado for r in evaluados}
        excedencias = [r.parametro for r in evaluados if r.estado == EXCEDE]
        if excedencias:
            estado = EXCEDE
        elif INDETERMINADO in estados or faltantes:
            estado = INDETERMINADO
        elif presentes:
            estado = CUMPLE
        else:
            estado = SIN_DATO
        salida.append(MuestraEvaluada(muestra, base.get("punto"), base.get("zona"), estado, excedencias,
                                      faltantes, evaluados, base))
    return salida


def resumen(muestras: list[MuestraEvaluada]) -> dict[str, Any]:
    total = len(muestras)
    por_estado: dict[str, int] = {}
    for m in muestras:
        por_estado[m.estado] = por_estado.get(m.estado, 0) + 1
    excedencias_param: dict[str, int] = {}
    maximos: dict[str, float] = {}
    for m in muestras:
        for r in m.resultados:
            if r.estado == EXCEDE:
                excedencias_param[r.parametro] = excedencias_param.get(r.parametro, 0) + 1
            if r.valor is not None and not r.menor_que:
                maximos[r.parametro] = max(maximos.get(r.parametro, r.valor), r.valor)
    puntos_excede = {m.punto for m in muestras if m.estado == EXCEDE and m.punto}
    puntos = {m.punto for m in muestras if m.punto}
    return {
        "muestras": total,
        "puntos": len(puntos),
        "por_estado": por_estado,
        "puntos_con_excedencia": sorted(puntos_excede),
        "excedencias_por_parametro": excedencias_param,
        "maximos": maximos,
        "porcentaje_cumplimiento": (por_estado.get(CUMPLE, 0) / total * 100) if total else 0.0,
    }
