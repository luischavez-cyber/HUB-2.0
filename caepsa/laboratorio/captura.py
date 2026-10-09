"""Persistencia de resultados extraídos o capturados manualmente."""
from __future__ import annotations

import csv
import io
from typing import Any

from ..normativa.nom138 import PARAMETROS, identificar_parametro
from ..proyectos import Proyecto
from .extractor import Extraccion

COLUMNAS_PLANTILLA = (
    "muestra", "punto", "zona", "profundidad_m", "utm_x", "utm_y", "utm_zona", "fecha_muestreo",
    "folio_lab", "parametro", "valor", "menor_que", "limite_deteccion", "unidad", "metodo", "pagina_pdf",
)


def guardar_extraccion(p: Proyecto, ext: Extraccion, utm_zona: str | None = None) -> int:
    """Guarda en la base del proyecto lo extraído del PDF. Devuelve resultados guardados."""
    n = 0
    for m in ext.muestras:
        if m.punto:
            p.guardar_punto(m.punto, zona=m.zona, utm_x=m.utm_x, utm_y=m.utm_y,
                            utm_zona=m.utm_zona or utm_zona)
        p.guardar_muestra(m.clave, m.punto, profundidad_m=m.profundidad_m, fecha_muestreo=m.fecha_muestreo,
                          folio_lab=m.folio_lab, origen="pdf", pagina_pdf=m.pagina)
        for clave, r in m.resultados.items():
            p.guardar_resultado(m.clave, clave, r.valor, menor_que=r.menor_que,
                                limite_deteccion=r.limite_deteccion, unidad=r.unidad or "mg/kg",
                                metodo=r.metodo, origen="pdf", pagina_pdf=r.pagina)
            n += 1
    return n


def _float(v: Any) -> float | None:
    if v is None or str(v).strip() == "":
        return None
    return float(str(v).replace(",", "").strip())


def _bool(v: Any) -> bool:
    return str(v).strip().lower() in ("1", "true", "si", "sí", "x", "<")


def importar_filas(p: Proyecto, filas: list[dict[str, Any]], origen: str = "manual") -> list[str]:
    """Importa filas en formato plantilla (una por resultado). Devuelve errores por fila."""
    errores: list[str] = []
    for i, f in enumerate(filas, start=2):
        try:
            muestra = str(f.get("muestra") or "").strip()
            if not muestra:
                raise ValueError("falta 'muestra'")
            punto = str(f.get("punto") or "").strip() or None
            if punto:
                p.guardar_punto(punto, zona=f.get("zona") or None, utm_x=_float(f.get("utm_x")),
                                utm_y=_float(f.get("utm_y")), utm_zona=f.get("utm_zona") or None)
            pagina = _float(f.get("pagina_pdf"))
            p.guardar_muestra(muestra, punto, profundidad_m=f.get("profundidad_m") or None,
                              fecha_muestreo=f.get("fecha_muestreo") or None, folio_lab=f.get("folio_lab") or None,
                              origen=origen, pagina_pdf=int(pagina) if pagina else None)
            texto_p = str(f.get("parametro") or "").strip()
            if not texto_p:
                continue
            clave = texto_p.upper() if texto_p.upper() in PARAMETROS else identificar_parametro(texto_p)
            if not clave:
                raise ValueError(f"parámetro no reconocido en la NOM-138: '{texto_p}'")
            valor_txt = str(f.get("valor") or "").strip()
            menor = _bool(f.get("menor_que")) or valor_txt.startswith("<")
            p.guardar_resultado(muestra, clave, _float(valor_txt.lstrip("<").strip()), menor_que=menor,
                                limite_deteccion=_float(f.get("limite_deteccion")),
                                unidad=f.get("unidad") or "mg/kg", metodo=f.get("metodo") or None,
                                origen=origen, pagina_pdf=int(pagina) if pagina else None)
        except (ValueError, KeyError) as e:
            errores.append(f"Fila {i}: {e}")
    return errores


def importar_csv(p: Proyecto, contenido: bytes | str) -> list[str]:
    texto = contenido.decode("utf-8-sig") if isinstance(contenido, bytes) else contenido
    return importar_filas(p, list(csv.DictReader(io.StringIO(texto))), origen="csv")


def plantilla_csv() -> str:
    return ",".join(COLUMNAS_PLANTILLA) + "\n"
