"""Metadatos de fotografías: fecha de toma y GPS (EXIF), conversión a UTM y punto más cercano."""
from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable

from PIL import ExifTags, Image, ImageOps

_EXIF_IFD = 0x8769
_GPS_IFD = 0x8825
_FECHA_ORIGINAL = 36867


@dataclass
class Metadatos:
    fecha_toma: str | None = None  # AAAA-MM-DD HH:MM:SS
    lat: float | None = None
    lon: float | None = None
    ancho: int | None = None
    alto: int | None = None


def _grados(valor: Any, ref: str) -> float:
    g, m, s = (float(x) for x in valor)
    dec = g + m / 60 + s / 3600
    return -dec if ref.upper() in ("S", "W") else dec


def leer_metadatos(contenido: bytes) -> Metadatos:
    """Lee fecha de toma y coordenadas GPS del EXIF. Campos ausentes quedan en None (nunca se suponen)."""
    md = Metadatos()
    try:
        img = Image.open(io.BytesIO(contenido))
    except (OSError, ValueError):
        return md
    img = ImageOps.exif_transpose(img) or img
    md.ancho, md.alto = img.size
    exif = img.getexif()
    fecha = exif.get_ifd(_EXIF_IFD).get(_FECHA_ORIGINAL) or exif.get(ExifTags.Base.DateTime)
    if fecha and re.match(r"\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}", str(fecha)):
        f = str(fecha)
        md.fecha_toma = f"{f[:4]}-{f[5:7]}-{f[8:10]}{f[10:19]}"
    gps = exif.get_ifd(_GPS_IFD)
    try:
        if gps.get(2) and gps.get(4):
            md.lat = _grados(gps[2], gps.get(1, "N"))
            md.lon = _grados(gps[4], gps.get(3, "E"))
    except (TypeError, ValueError, ZeroDivisionError):
        md.lat = md.lon = None
    return md


def preparar_imagen(contenido: bytes, lado_max: int = 1568) -> bytes:
    """JPEG orientado y reducido para enviarlo al modelo (menos tokens, mismo contenido visual)."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(contenido)))
    img = img.convert("RGB")
    img.thumbnail((lado_max, lado_max))
    salida = io.BytesIO()
    img.save(salida, format="JPEG", quality=85)
    return salida.getvalue()


def miniatura(contenido: bytes, lado_max: int = 480) -> bytes:
    return preparar_imagen(contenido, lado_max)


# ---------------------------------------------------------------------------- UTM (WGS84)
_A = 6378137.0
_F = 1 / 298.257223563
_K0 = 0.9996


def zona_utm(lon: float) -> int:
    return int((lon + 180) // 6) + 1


def numero_zona(texto: str | None) -> int | None:
    m = re.match(r"\s*(\d{1,2})", texto or "")
    return int(m.group(1)) if m else None


def a_utm(lat: float, lon: float, zona: int | None = None) -> tuple[float, float, int]:
    """Geográficas WGS84 → UTM (serie de Krüger). Si se indica la zona del proyecto se usa esa."""
    zona = zona or zona_utm(lon)
    lon0 = math.radians((zona - 1) * 6 - 180 + 3)
    n = _F / (2 - _F)
    a_ = _A / (1 + n) * (1 + n**2 / 4 + n**4 / 64)
    alfa = (n / 2 - 2 * n**2 / 3 + 5 * n**3 / 16, 13 * n**2 / 48 - 3 * n**3 / 5, 61 * n**3 / 240)
    phi, lam = math.radians(lat), math.radians(lon) - lon0
    e = 2 * math.sqrt(n) / (1 + n)
    t = math.sinh(math.atanh(math.sin(phi)) - e * math.atanh(e * math.sin(phi)))
    xi_p = math.atan2(t, math.cos(lam))
    eta_p = math.atanh(math.sin(lam) / math.sqrt(1 + t * t))
    xi, eta = xi_p, eta_p
    for j, a_j in enumerate(alfa, start=1):
        xi += a_j * math.sin(2 * j * xi_p) * math.cosh(2 * j * eta_p)
        eta += a_j * math.cos(2 * j * xi_p) * math.sinh(2 * j * eta_p)
    este = 500000 + _K0 * a_ * eta
    norte = _K0 * a_ * xi + (10_000_000 if lat < 0 else 0)
    return este, norte, zona


def punto_cercano(x: float, y: float, puntos: Iterable[dict[str, Any]],
                  radio_m: float = 30.0) -> tuple[str, float] | None:
    """Punto de muestreo más cercano dentro del radio (m), o None."""
    mejor: tuple[str, float] | None = None
    for p in puntos:
        if p.get("utm_x") is None or p.get("utm_y") is None:
            continue
        d = math.hypot(p["utm_x"] - x, p["utm_y"] - y)
        if d <= radio_m and (mejor is None or d < mejor[1]):
            mejor = (p["clave"], d)
    return mejor
