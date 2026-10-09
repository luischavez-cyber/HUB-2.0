"""Módulo 2 — Extracción de resultados de laboratorio desde PDF (pdfplumber).

Reconoce dos disposiciones comunes en informes de laboratorio acreditado:

* **Por muestra**: cada página (o bloque) corresponde a una muestra, con sus
  datos de identificación en el encabezado y una tabla parámetro/resultado.
* **Matricial**: una tabla con los parámetros en filas y las muestras en columnas.

La extracción es heurística: cada campo no recuperado se reporta en
``faltantes`` para que el usuario lo capture manualmente. Ningún valor se
inventa ni se infiere fuera de lo que aparece en el PDF.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

import pdfplumber

from ..normativa.nom138 import identificar_parametro

CAMPOS_MUESTRA = ("punto", "profundidad_m", "utm_x", "utm_y", "fecha_muestreo")


@dataclass
class ResultadoExtraido:
    valor: float | None
    menor_que: bool = False
    limite_deteccion: float | None = None
    unidad: str | None = None
    metodo: str | None = None
    pagina: int | None = None
    texto: str = ""


@dataclass
class MuestraExtraida:
    clave: str
    pagina: int | None = None
    punto: str | None = None
    zona: str | None = None
    profundidad_m: str | None = None
    utm_x: float | None = None
    utm_y: float | None = None
    utm_zona: str | None = None
    fecha_muestreo: str | None = None
    folio_lab: str | None = None
    resultados: dict[str, ResultadoExtraido] = field(default_factory=dict)

    @property
    def faltantes(self) -> list[str]:
        f = [c for c in CAMPOS_MUESTRA if getattr(self, c) in (None, "")]
        if not self.resultados:
            f.append("resultados")
        return f


@dataclass
class Extraccion:
    muestras: list[MuestraExtraida]
    metodos: dict[str, str]
    paginas: int
    texto: list[str]
    advertencias: list[str] = field(default_factory=list)


# --------------------------------------------------------------------- utilidades
_NUM = r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-+]?\d+(?:\.\d+)?"
_RE_NUM = re.compile(_NUM)
_RE_ND = re.compile(r"^\s*(N\.?\s*D\.?|NO\s+DETECTADO|<\s*L\.?\s*[DC]\.?\s*[MC]?\.?)\s*$", re.I)
_RE_MENOR = re.compile(rf"^\s*<\s*({_NUM})\s*$")
_RE_METODO = re.compile(r"\b(NMX-AA-\d{2,3}-SCFI-\d{4}|EPA[\s-]*\d{4}\s?[A-Z]?)\b", re.I)


def _num(texto: str) -> float | None:
    m = _RE_NUM.search(texto or "")
    return float(m.group().replace(",", "")) if m else None


def interpretar_valor(celda: str | None) -> tuple[float | None, bool] | None:
    """Convierte la celda de resultado en (valor, menor_que). None si no es un resultado."""
    if celda is None:
        return None
    t = str(celda).strip()
    if not t:
        return None
    if _RE_ND.match(t):
        return None, True
    m = _RE_MENOR.match(t)
    if m:
        return float(m.group(1).replace(",", "")), True
    if re.fullmatch(rf"\s*({_NUM})\s*(mg\s*/\s*kg.*)?", t, re.I):
        return _num(t), False
    return None


_ETIQUETAS: dict[str, re.Pattern[str]] = {
    "clave": re.compile(
        r"(?:identificaci[oó]n\s+(?:de\s+(?:la\s+)?muestra|del\s+cliente)|clave\s+de\s+(?:la\s+)?muestra|"
        r"id\.?\s+(?:de\s+)?(?:la\s+)?muestra|muestra)\s*[:#]\s*([A-Z0-9][\w./-]*)", re.I),
    "folio_lab": re.compile(r"(?:folio|n[uú]mero\s+de\s+laboratorio|no\.\s*lab\.?)\s*[:#]?\s*([A-Z0-9][\w/-]*)", re.I),
    "punto": re.compile(r"punto(?:\s+de\s+muestreo)?\s*[:#]\s*([A-Z0-9][\w./-]*)", re.I),
    "zona": re.compile(r"\b(zona\s*\d+|periferia)\b", re.I),
    "profundidad_m": re.compile(rf"profundidad[^:\n]*:\s*((?:{_NUM})(?:\s*-\s*(?:{_NUM}))?)\s*m?", re.I),
    "utm_x": re.compile(rf"(?:\bX\b|\bEste\b|\bE\b)\s*[:=]?\s*({_NUM})", re.I),
    "utm_y": re.compile(rf"(?:\bY\b|\bNorte\b|\bN\b)\s*[:=]?\s*({_NUM})", re.I),
    "utm_zona": re.compile(r"(?:zona\s+UTM|UTM)\s*[:]?\s*(\d{1,2}\s?[C-X])\b", re.I),
    "fecha_muestreo": re.compile(
        r"fecha\s+de\s+muestreo\s*[:]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})", re.I),
}


def _metadatos(texto: str) -> dict[str, Any]:
    datos: dict[str, Any] = {}
    for campo, rx in _ETIQUETAS.items():
        m = rx.search(texto)
        if not m:
            continue
        v: Any = m.group(1).strip()
        if campo in ("utm_x", "utm_y"):
            v = float(v.replace(",", ""))
            # Coordenadas UTM en México: Este 6 dígitos, Norte 7 dígitos.
            if campo == "utm_x" and not 100_000 <= v <= 900_000:
                continue
            if campo == "utm_y" and not 1_000_000 <= v <= 3_700_000:
                continue
        if campo == "zona":
            v = v.title()
        datos[campo] = v
    return datos


# --------------------------------------------------------------------- tablas
_ENC = {
    "resultado": re.compile(r"resultado|concentraci[oó]n|valor", re.I),
    "ld": re.compile(r"l[ií]mite\s+de\s+(detecci[oó]n|cuantificaci[oó]n)|\bL\.?\s*[DC]\.?\s*[MC]?\.?\b", re.I),
    "unidad": re.compile(r"unidad", re.I),
    "metodo": re.compile(r"m[eé]todo", re.I),
    "parametro": re.compile(r"par[aá]metro|analito|determinaci[oó]n|compuesto", re.I),
}


def _celdas(fila: list[Any]) -> list[str]:
    return [" ".join(str(c).split()) if c is not None else "" for c in fila]


def _encabezado(tabla: list[list[str]]) -> tuple[int, dict[str, int]] | None:
    for i, fila in enumerate(tabla[:4]):
        cols: dict[str, int] = {}
        for j, c in enumerate(fila):
            for nombre, rx in _ENC.items():
                if nombre not in cols and rx.search(c):
                    cols[nombre] = j
                    break
        if "parametro" in cols or "resultado" in cols:
            return i, cols
    return None


def _col_parametro(tabla: list[list[str]]) -> int | None:
    mejor, n_mejor = None, 0
    for j in range(max(len(f) for f in tabla)):
        n = sum(1 for f in tabla if j < len(f) and identificar_parametro(f[j]))
        if n > n_mejor:
            mejor, n_mejor = j, n
    return mejor


def _filas_metadato(tabla: list[list[str]], col_p: int) -> dict[str, list[str]]:
    """Filas tipo 'Profundidad', 'Coordenada X'… en tablas matriciales."""
    claves = {
        "profundidad_m": re.compile(r"profundidad", re.I),
        "utm_x": re.compile(r"\b(x|este|coordenada\s+x)\b", re.I),
        "utm_y": re.compile(r"\b(y|norte|coordenada\s+y)\b", re.I),
        "fecha_muestreo": re.compile(r"fecha\s+de\s+muestreo", re.I),
        "punto": re.compile(r"punto", re.I),
        "zona": re.compile(r"^zona$", re.I),
    }
    out: dict[str, list[str]] = {}
    for f in tabla:
        if col_p < len(f):
            for campo, rx in claves.items():
                if rx.search(f[col_p]) and campo not in out:
                    out[campo] = f
    return out


# --------------------------------------------------------------------- extracción
def extraer(origen: str | Path | bytes | BinaryIO) -> Extraccion:
    if isinstance(origen, bytes):
        origen = io.BytesIO(origen)
    muestras: dict[str, MuestraExtraida] = {}
    metodos: dict[str, str] = {}
    textos: list[str] = []
    advertencias: list[str] = []
    actual: MuestraExtraida | None = None

    with pdfplumber.open(origen) as pdf:
        n_paginas = len(pdf.pages)
        for num, pagina in enumerate(pdf.pages, start=1):
            texto = pagina.extract_text() or ""
            textos.append(texto)
            meta = _metadatos(texto)
            if meta.get("clave"):
                clave = meta["clave"]
                actual = muestras.setdefault(clave, MuestraExtraida(clave=clave, pagina=num))
                for k, v in meta.items():
                    if k != "clave" and getattr(actual, k, None) in (None, ""):
                        setattr(actual, k, v)

            tablas = [[_celdas(f) for f in t] for t in pagina.extract_tables() if t]
            tablas_usadas = False
            for tabla in tablas:
                if _procesar_matriz(tabla, num, muestras, metodos):
                    tablas_usadas = True
                elif actual and _procesar_por_muestra(tabla, num, actual, metodos):
                    tablas_usadas = True
            if not tablas_usadas and actual:
                _procesar_texto(texto, num, actual, metodos)

        if not muestras:
            advertencias.append(
                "No se identificaron muestras. Verifique que el PDF tenga texto (no escaneado) "
                "o capture los resultados manualmente.")

    for m in muestras.values():
        for clave, r in m.resultados.items():
            if not r.metodo and clave in metodos:
                r.metodo = metodos[clave]
    return Extraccion(list(muestras.values()), metodos, n_paginas, textos, advertencias)


def _procesar_matriz(tabla: list[list[str]], pagina: int, muestras: dict[str, MuestraExtraida],
                     metodos: dict[str, str]) -> bool:
    if len(tabla) < 2:
        return False
    col_p = _col_parametro(tabla)
    if col_p is None:
        return False
    enc = _encabezado(tabla)
    fila_enc = enc[0] if enc else 0
    cabecera = tabla[fila_enc]
    if identificar_parametro(cabecera[col_p]) if col_p < len(cabecera) else True:
        return False  # la primera fila ya es de resultados: no hay cabecera de muestras
    cols_conocidas = set(enc[1].values()) if enc else set()
    cols_muestra = [j for j, c in enumerate(cabecera)
                    if j != col_p and j not in cols_conocidas and c and not identificar_parametro(c)
                    and interpretar_valor(c) is None and not re.match(r"mg\s*/", c, re.I)]
    if len(cols_muestra) < 2:
        return False

    col_unidad = enc[1].get("unidad") if enc else None
    col_metodo = enc[1].get("metodo") if enc else None
    col_ld = enc[1].get("ld") if enc else None
    meta = _filas_metadato(tabla, col_p)
    for j in cols_muestra:
        clave = cabecera[j]
        m = muestras.setdefault(clave, MuestraExtraida(clave=clave, pagina=pagina))
        for campo, fila in meta.items():
            if j < len(fila) and fila[j] and getattr(m, campo) in (None, ""):
                valor: Any = fila[j]
                if campo in ("utm_x", "utm_y"):
                    valor = _num(valor)
                setattr(m, campo, valor)
    for fila in tabla[fila_enc + 1:]:
        clave_p = identificar_parametro(fila[col_p]) if col_p < len(fila) else None
        if not clave_p:
            continue
        metodo = _metodo(fila, col_metodo)
        if metodo:
            metodos.setdefault(clave_p, metodo)
        ld = _num(fila[col_ld]) if col_ld is not None and col_ld < len(fila) else None
        for j in cols_muestra:
            v = interpretar_valor(fila[j]) if j < len(fila) else None
            if v is None:
                continue
            valor, menor = v
            muestras[cabecera[j]].resultados[clave_p] = ResultadoExtraido(
                valor, menor, ld if ld is not None else (valor if menor else None),
                _celda(fila, col_unidad), metodo, pagina, " | ".join(fila))
    return True


def _procesar_por_muestra(tabla: list[list[str]], pagina: int, m: MuestraExtraida,
                          metodos: dict[str, str]) -> bool:
    col_p = _col_parametro(tabla)
    if col_p is None:
        return False
    enc = _encabezado(tabla)
    cols = enc[1] if enc else {}
    usado = False
    for fila in tabla[(enc[0] + 1) if enc else 0:]:
        clave_p = identificar_parametro(fila[col_p]) if col_p < len(fila) else None
        if not clave_p:
            continue
        if "resultado" in cols:
            v = interpretar_valor(_celda(fila, cols["resultado"]))
        else:
            v = next((x for x in (interpretar_valor(c) for c in fila[col_p + 1:]) if x), None)
        if v is None:
            continue
        valor, menor = v
        ld = _num(_celda(fila, cols.get("ld")) or "") if "ld" in cols else None
        metodo = _metodo(fila, cols.get("metodo"))
        if metodo:
            metodos.setdefault(clave_p, metodo)
        m.resultados[clave_p] = ResultadoExtraido(
            valor, menor, ld if ld is not None else (valor if menor else None),
            _celda(fila, cols.get("unidad")), metodo, pagina, " | ".join(fila))
        usado = True
    return usado


def _procesar_texto(texto: str, pagina: int, m: MuestraExtraida, metodos: dict[str, str]) -> None:
    for linea in texto.splitlines():
        tokens = linea.split()
        for corte in range(len(tokens) - 1, 0, -1):
            clave_p = identificar_parametro(" ".join(tokens[:corte]))
            if not clave_p:
                continue
            resto = " ".join(tokens[corte:])
            mv = re.match(rf"\s*(<\s*(?:{_NUM})|N\.?D\.?|(?:{_NUM}))", resto, re.I)
            v = interpretar_valor(mv.group(1)) if mv else None
            if v is not None and clave_p not in m.resultados:
                metodo = (_RE_METODO.search(resto) or [None])[0]
                if metodo:
                    metodos.setdefault(clave_p, metodo)
                unidad = re.search(r"mg\s*/\s*kg(?:\s*b\.?\s*s\.?)?", resto, re.I)
                m.resultados[clave_p] = ResultadoExtraido(
                    v[0], v[1], v[0] if v[1] else None, unidad.group() if unidad else None,
                    metodo, pagina, linea)
            break


def _celda(fila: list[str], j: int | None) -> str | None:
    return fila[j] if j is not None and j < len(fila) and fila[j] else None


def _metodo(fila: list[str], j: int | None) -> str | None:
    c = _celda(fila, j)
    if c:
        return c
    m = _RE_METODO.search(" ".join(fila))
    return m.group(1) if m else None
