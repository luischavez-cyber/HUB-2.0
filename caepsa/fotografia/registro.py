"""Persistencia de fotografías del proyecto y orquestación de la clasificación."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable

from ..proyectos import Proyecto
from .clasificador import CATEGORIAS, MAX_PALABRAS, Clasificacion, ErrorClasificacion, clasificar, contar_palabras
from .metadatos import a_utm, leer_metadatos, numero_zona, punto_cercano

RADIO_PUNTO_M = 30.0
_EDITABLES = ("categoria", "pie", "punto", "revisada", "incluir", "orden", "observacion")


def registrar_fotografia(p: Proyecto, nombre: str, contenido: bytes) -> int:
    """Guarda la foto, lee su EXIF y la asocia al punto de muestreo más cercano si trae GPS."""
    sha = hashlib.sha256(contenido).hexdigest()
    previa = p.con.execute(
        "SELECT f.id FROM fotografias f JOIN documentos d ON d.id = f.documento_id WHERE d.sha256=?", (sha,)
    ).fetchone()
    if previa:
        return int(previa["id"])
    p.guardar_documento("fotografia", nombre, contenido)
    doc_id = p.con.execute("SELECT id FROM documentos WHERE sha256=? ORDER BY id DESC", (sha,)).fetchone()["id"]
    md = leer_metadatos(contenido)
    x = y = None
    punto = None
    if md.lat is not None and md.lon is not None:
        x, y, _ = a_utm(md.lat, md.lon, numero_zona(p.ficha().get("utm_zona")))
        puntos = [dict(r) for r in p.con.execute("SELECT clave, utm_x, utm_y FROM puntos")]
        cercano = punto_cercano(x, y, puntos, RADIO_PUNTO_M)
        punto = cercano[0] if cercano else None
    with p.con:
        cur = p.con.execute(
            "INSERT INTO fotografias (documento_id, fecha_toma, lat, lon, utm_x, utm_y, punto, punto_origen)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (doc_id, md.fecha_toma, md.lat, md.lon, x, y, punto, "gps" if punto else None),
        )
        p.registrar_cambio("fotografia", nombre, "crear", None,
                           {"fecha_toma": md.fecha_toma, "utm_x": x, "utm_y": y, "punto": punto})
    return int(cur.lastrowid or 0)


def listar_fotografias(p: Proyecto, categoria: str | None = None, solo_incluidas: bool = False) -> list[dict[str, Any]]:
    filas = [dict(r) for r in p.con.execute(
        "SELECT f.*, d.nombre, d.ruta FROM fotografias f JOIN documentos d ON d.id = f.documento_id")]
    if categoria:
        filas = [f for f in filas if f["categoria"] == categoria]
    if solo_incluidas:
        filas = [f for f in filas if f["incluir"]]
    orden_cat = {c: i for i, c in enumerate(CATEGORIAS)}
    return sorted(filas, key=lambda f: (orden_cat.get(f["categoria"], len(orden_cat)),
                                        f["orden"] if f["orden"] is not None else 10**6,
                                        f["fecha_toma"] or "", f["nombre"], f["id"]))


def obtener(p: Proyecto, foto_id: int) -> dict[str, Any]:
    fila = next((f for f in listar_fotografias(p) if f["id"] == foto_id), None)
    if not fila:
        raise KeyError(f"No existe la fotografía {foto_id}")
    return fila


def actualizar_fotografia(p: Proyecto, foto_id: int, origen: str = "manual", **campos: Any) -> dict[str, Any]:
    """Actualiza campos editables. Cambios manuales de categoría o pie quedan marcados como 'manual'."""
    desconocidos = set(campos) - set(_EDITABLES)
    if desconocidos:
        raise ValueError(f"Campos no editables: {', '.join(sorted(desconocidos))}")
    if campos.get("categoria") is not None and campos["categoria"] not in CATEGORIAS:
        raise ValueError(f"Categoría inválida. Opciones: {', '.join(CATEGORIAS)}")
    if campos.get("pie") is not None:
        campos["pie"] = " ".join(str(campos["pie"]).split()).rstrip(".")
    previo = obtener(p, foto_id)
    cambios = {k: v for k, v in campos.items() if previo[k] != v}
    if not cambios:
        return {}
    if "categoria" in cambios:
        cambios["categoria_origen"] = origen
    if "pie" in cambios:
        cambios["pie_origen"] = origen
    if "punto" in cambios:
        cambios["punto_origen"] = origen
    with p.con:
        sets = ", ".join(f"{k}=?" for k in cambios)
        p.con.execute(f"UPDATE fotografias SET {sets} WHERE id=?", (*cambios.values(), foto_id))
        p.registrar_cambio("fotografia", previo["nombre"], "actualizar",
                           {k: previo.get(k) for k in cambios}, cambios)
    return cambios


def contexto_proyecto(p: Proyecto, foto: dict[str, Any]) -> str:
    ficha = p.ficha()
    lineas = [f"{etq}: {ficha[k]}" for k, etq in (
        ("sitio", "Sitio"), ("municipio", "Municipio"), ("estado", "Estado"),
        ("ubicacion", "Ubicación"), ("producto", "Producto derramado")) if ficha.get(k)]
    if foto.get("punto"):
        zona = p.con.execute("SELECT zona FROM puntos WHERE clave=?", (foto["punto"],)).fetchone()
        lineas.append(f"Fotografía tomada junto al punto de muestreo {foto['punto']}"
                      + (f" ({zona['zona']})" if zona and zona["zona"] else ""))
    return "\n".join(lineas)


def aplicar_clasificacion(p: Proyecto, foto: dict[str, Any], c: Clasificacion, forzar: bool = False) -> None:
    """Guarda la propuesta de la IA sin pisar correcciones manuales, salvo que se fuerce."""
    campos: dict[str, Any] = {}
    if forzar or foto["categoria_origen"] != "manual":
        campos["categoria"] = c.categoria
    if forzar or foto["pie_origen"] != "manual":
        campos["pie"] = c.pie
    obs = c.observacion.strip()
    if contar_palabras(c.pie) > MAX_PALABRAS:
        obs = (obs + "; " if obs else "") + f"pie con más de {MAX_PALABRAS} palabras"
    campos["observacion"] = obs or None
    actualizar_fotografia(p, foto["id"], origen="ia", **campos)
    with p.con:
        p.con.execute("UPDATE fotografias SET confianza=?, revisada=0 WHERE id=?", (c.confianza, foto["id"]))


def clasificar_fotografias(p: Proyecto, cliente: Any | None = None, ids: list[int] | None = None,
                           forzar: bool = False,
                           al_avance: Callable[[int, int, dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Clasifica las fotografías indicadas o, por omisión, las que no tienen categoría o pie."""
    fotos = listar_fotografias(p)
    objetivo = [f for f in fotos if f["id"] in ids] if ids else [f for f in fotos if not f["categoria"] or not f["pie"]]
    hechas, errores = 0, []
    for i, f in enumerate(objetivo, start=1):
        try:
            c = clasificar(Path(f["ruta"]).read_bytes(), contexto_proyecto(p, f), cliente=cliente)
            aplicar_clasificacion(p, f, c, forzar=forzar)
            hechas += 1
        except (ErrorClasificacion, OSError) as e:
            errores.append(f"{f['nombre']}: {e}")
        if al_avance:
            al_avance(i, len(objetivo), f)
    return {"procesadas": hechas, "pendientes_previas": len(objetivo), "errores": errores}


def diagnostico(p: Proyecto) -> dict[str, Any]:
    fotos = listar_fotografias(p)
    incluidas = [f for f in fotos if f["incluir"]]
    return {
        "total": len(fotos),
        "sin_clasificar": [f["id"] for f in incluidas if not f["categoria"] or not f["pie"]],
        "sin_revisar": [f["id"] for f in incluidas if f["categoria"] and f["pie"] and not f["revisada"]],
        "pies_largos": [f["id"] for f in incluidas if f["pie"] and contar_palabras(f["pie"]) > MAX_PALABRAS],
        "por_categoria": {c: sum(1 for f in incluidas if f["categoria"] == c) for c in CATEGORIAS},
    }
