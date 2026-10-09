"""Módulo 5 — Orquestación de la revisión técnica y su historial."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from ..fotografia.registro import diagnostico as diagnostico_fotos
from ..normativa.evaluacion import evaluar, resumen
from ..normativa.nom138 import PARAMETROS
from ..proyectos import Proyecto
from . import revisor_ia
from .documento import leer
from .indice import Hallazgo, calcular_ict
from .verificaciones import verificar

ESTADOS = ("abierto", "atendido", "descartado")


def contexto_proyecto(p: Proyecto) -> str:
    """Resumen de los datos del proyecto que el revisor puede usar como referencia."""
    f = p.ficha()
    usos = p.usos_suelo()
    lineas = [f"{k}: {f[k]}" for k in ("nombre", "cliente", "sitio", "municipio", "estado", "ubicacion", "producto",
                                        "expediente", "laboratorio", "utm_zona") if f.get(k)]
    if usos:
        lineas.append("Uso de suelo: " + " / ".join(u.etiqueta for u in usos))
    c = p.conteos()
    lineas.append(f"Base del proyecto: {c['puntos']} puntos de muestreo, {c['muestras']} muestras, "
                  f"{c['resultados']} resultados analíticos")
    filas = p.tabla_resultados()
    if usos and any(x["parametro"] for x in filas):
        ev = evaluar(filas, usos, f.get("producto"))
        s = resumen(ev)
        lineas.append("Evaluación NOM-138 (motor de la plataforma): " + ", ".join(
            f"{k}: {v}" for k, v in s["por_estado"].items()))
        for m in ev:
            if m.excedencias:
                vals = ", ".join(f"{PARAMETROS[r.parametro].nombre} {r.valor:g} (LMP {r.lmp:g})"
                                 for r in m.resultados if r.parametro in m.excedencias)
                lineas.append(f"  Excede: {m.muestra} · {m.punto or ''} · {m.zona or ''} · {vals}")
    fotos = diagnostico_fotos(p)
    if fotos["total"]:
        lineas.append(f"Fotografías registradas: {fotos['total']}")
    return "\n".join(lineas)


def revisar_borrador(p: Proyecto, documento_id: int, usar_ia: bool = True, cliente: Any | None = None,
                     hoy: date | None = None) -> int:
    """Revisa un borrador cargado al proyecto, guarda la revisión y devuelve su id."""
    doc_row = next((d for d in p.documentos() if d["id"] == documento_id), None)
    if not doc_row:
        raise KeyError(f"No existe el documento {documento_id}")
    doc = leer(Path(doc_row["ruta"]), doc_row["nombre"])
    hallazgos = verificar(doc, p, hoy)
    resumen_ia, fortalezas, aviso, modelo = "", [], None, None
    if usar_ia:
        try:
            r = revisor_ia.revisar(doc, contexto_proyecto(p), hallazgos, cliente=cliente)
            hallazgos += r.hallazgos
            resumen_ia, fortalezas, modelo = r.resumen, r.fortalezas, revisor_ia.MODELO
        except revisor_ia.ErrorRevision as e:
            aviso = f"Revisión con IA no realizada: {e}"
    ict = calcular_ict(hallazgos)
    with p.con:
        cur = p.con.execute(
            "INSERT INTO revisiones (documento_id, usuario, ict, subindices, interpretacion, resumen, fortalezas,"
            " usa_ia, modelo, aviso) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (documento_id, p.usuario, ict["ict"], json.dumps(ict["subindices"]), ict["interpretacion"], resumen_ia,
             json.dumps(fortalezas, ensure_ascii=False), int(usar_ia and aviso is None), modelo, aviso))
        rev_id = int(cur.lastrowid or 0)
        p.con.executemany(
            "INSERT INTO hallazgos (revision_id, origen, categoria, criticidad, ubicacion, descripcion, evidencia,"
            " riesgo, recomendacion, referencia, evidencia_localizada, estado, nota) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(rev_id, h.origen, h.categoria, h.criticidad, h.ubicacion, h.descripcion, h.evidencia, h.riesgo,
              h.recomendacion, h.referencia, None if h.evidencia_localizada is None else int(h.evidencia_localizada),
              h.estado, h.nota) for h in hallazgos])
        p.registrar_cambio("revision", doc_row["nombre"], "crear", None,
                           {"revision_id": rev_id, "ict": ict["ict"], "hallazgos": len(hallazgos)})
    return rev_id


def listar_revisiones(p: Proyecto) -> list[dict[str, Any]]:
    filas = p.con.execute(
        "SELECT r.*, d.nombre AS documento FROM revisiones r JOIN documentos d ON d.id = r.documento_id "
        "ORDER BY r.id DESC").fetchall()
    out = []
    for f in filas:
        r = dict(f)
        r["subindices"] = json.loads(r["subindices"])
        r["fortalezas"] = json.loads(r["fortalezas"] or "[]")
        r["ict_vigente"] = calcular_ict(hallazgos_de(p, r["id"]))["ict"]
        out.append(r)
    return out


def obtener_revision(p: Proyecto, revision_id: int) -> dict[str, Any]:
    r = next((x for x in listar_revisiones(p) if x["id"] == revision_id), None)
    if r is None:
        raise KeyError(f"No existe la revisión {revision_id}")
    return r


def hallazgos_de(p: Proyecto, revision_id: int) -> list[Hallazgo]:
    filas = p.con.execute("SELECT * FROM hallazgos WHERE revision_id=? ORDER BY id", (revision_id,)).fetchall()
    return [Hallazgo(f["origen"], f["categoria"], f["criticidad"], f["ubicacion"] or "", f["descripcion"],
                     evidencia=f["evidencia"] or "", riesgo=f["riesgo"] or "", recomendacion=f["recomendacion"] or "",
                     referencia=f["referencia"] or "",
                     evidencia_localizada=None if f["evidencia_localizada"] is None else bool(f["evidencia_localizada"]),
                     estado=f["estado"], nota=f["nota"] or "", id=f["id"]) for f in filas]


def actualizar_hallazgo(p: Proyecto, hallazgo_id: int, estado: str, nota: str = "") -> None:
    if estado not in ESTADOS:
        raise ValueError(f"Estado inválido. Opciones: {', '.join(ESTADOS)}")
    previo = p.con.execute("SELECT estado, nota FROM hallazgos WHERE id=?", (hallazgo_id,)).fetchone()
    if not previo:
        raise KeyError(f"No existe el hallazgo {hallazgo_id}")
    if estado == "descartado" and not nota.strip():
        raise ValueError("Para descartar un hallazgo indique la justificación en la nota")
    if (previo["estado"], previo["nota"] or "") == (estado, nota):
        return
    with p.con:
        p.con.execute("UPDATE hallazgos SET estado=?, nota=? WHERE id=?", (estado, nota, hallazgo_id))
        p.registrar_cambio("hallazgo", str(hallazgo_id), "actualizar", dict(previo), {"estado": estado, "nota": nota})
