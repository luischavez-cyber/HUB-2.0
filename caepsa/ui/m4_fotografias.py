"""Módulo 4 — Gestión Fotográfica (pantalla)."""
import os
from pathlib import Path

import anthropic
import streamlit as st

from caepsa.fotografia.clasificador import CATEGORIAS, MAX_PALABRAS, contar_palabras
from caepsa.fotografia.metadatos import miniatura
from caepsa.fotografia.registro import (
    actualizar_fotografia, clasificar_fotografias, diagnostico, listar_fotografias, registrar_fotografia)
from caepsa.fotografia.seccion import generar_word
from caepsa.ui.comun import requiere_proyecto

POR_PAGINA = 24
SIN_CLASIFICAR = "— sin clasificar —"

p = requiere_proyecto()
st.title("Gestión Fotográfica")
st.caption(f"Proyecto: {p.ficha().get('nombre', p.clave)} · Pies de foto de máximo {MAX_PALABRAS} palabras")


@st.cache_data(show_spinner=False, max_entries=2000)
def _mini(ruta: str, _mtime: float) -> bytes:
    return miniatura(Path(ruta).read_bytes())


with st.expander("➕ Cargar fotografías", expanded=not listar_fotografias(p)):
    archivos = st.file_uploader("Fotografías del proyecto", type=["jpg", "jpeg", "png"], accept_multiple_files=True)
    if archivos and st.button("Registrar fotografías", type="primary"):
        barra = st.progress(0.0)
        for i, a in enumerate(archivos, start=1):
            registrar_fotografia(p, a.name, a.getvalue())
            barra.progress(i / len(archivos))
        st.success(f"{len(archivos)} fotografía(s) registradas. Las repetidas se detectan y no se duplican.")
        st.rerun()

d = diagnostico(p)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Fotografías", d["total"])
c2.metric("Sin clasificar", len(d["sin_clasificar"]))
c3.metric("Pendientes de revisión", len(d["sin_revisar"]))
c4.metric(f"Pies > {MAX_PALABRAS} palabras", len(d["pies_largos"]))

hay_api = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
a1, a2 = st.columns(2)
if a1.button("🤖 Clasificar pendientes con IA", disabled=not hay_api or not d["sin_clasificar"],
             help=None if hay_api else "Configure ANTHROPIC_API_KEY para usar la clasificación automática"):
    barra = st.progress(0.0, text="Clasificando…")
    try:
        res = clasificar_fotografias(
            p, al_avance=lambda i, n, f: barra.progress(i / n, text=f"{i}/{n} · {f['nombre']}"))
        st.success(f"{res['procesadas']} fotografía(s) clasificadas.")
        for e in res["errores"]:
            st.warning(e)
    except anthropic.APIError as exc:
        st.error(f"Error al consultar el modelo: {exc}")
    st.rerun()
contenido, avisos = generar_word(p) if d["total"] else (b"", [])
a2.download_button("📄 Sección fotográfica (Word)", contenido, f"{p.clave}_seccion_fotografica.docx",
                   "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                   disabled=not d["total"])
for a in avisos:
    st.caption(f"⚠️ {a}")

st.markdown("**Fotografías por categoría:** " + " · ".join(
    f"{CATEGORIAS[c][0]}: {n}" for c, n in d["por_categoria"].items()))

f1, f2 = st.columns(2)
opciones_cat = [SIN_CLASIFICAR, *CATEGORIAS]
filtro_cat = f1.multiselect("Categoría", opciones_cat, default=opciones_cat,
                            format_func=lambda c: c if c == SIN_CLASIFICAR else CATEGORIAS[c][0])
filtro_rev = f2.radio("Revisión", ["Todas", "Pendientes de revisión", "Revisadas"], horizontal=True)

fotos = [f for f in listar_fotografias(p)
         if (f["categoria"] or SIN_CLASIFICAR) in filtro_cat
         and (filtro_rev == "Todas" or bool(f["revisada"]) == (filtro_rev == "Revisadas"))]
if not fotos:
    st.info("No hay fotografías con estos filtros.")
    st.stop()

paginas = max(1, -(-len(fotos) // POR_PAGINA))
pagina = st.number_input("Página", 1, paginas, 1) if paginas > 1 else 1
visibles = fotos[(pagina - 1) * POR_PAGINA: pagina * POR_PAGINA]

with st.form("fotos"):
    valores = {}
    for i in range(0, len(visibles), 3):
        cols = st.columns(3)
        for col, f in zip(cols, visibles[i:i + 3]):
            with col.container(border=True):
                ruta = Path(f["ruta"])
                st.image(_mini(str(ruta), ruta.stat().st_mtime), width="stretch")
                cat = st.selectbox("Categoría", opciones_cat,
                                   index=opciones_cat.index(f["categoria"] or SIN_CLASIFICAR),
                                   format_func=lambda c: c if c == SIN_CLASIFICAR else CATEGORIAS[c][0],
                                   key=f"cat{f['id']}")
                pie = st.text_area("Pie de foto", f["pie"] or "", key=f"pie{f['id']}", height=80)
                n = contar_palabras(pie)
                st.caption((f":red[{n} palabras — máximo {MAX_PALABRAS}]" if n > MAX_PALABRAS else f"{n} palabras")
                           + (f" · IA ({f['confianza']})" if f["pie_origen"] == "ia" and f["confianza"] else "")
                           + (f" · Punto {f['punto']}" if f["punto"] else "")
                           + (f" · {f['fecha_toma']}" if f["fecha_toma"] else ""))
                if f["observacion"]:
                    st.caption(f"🔎 {f['observacion']}")
                k1, k2 = st.columns(2)
                incluir = k1.checkbox("Incluir", bool(f["incluir"]), key=f"inc{f['id']}")
                revisada = k2.checkbox("Revisada", bool(f["revisada"]), key=f"rev{f['id']}")
                valores[f["id"]] = (f, cat, pie, incluir, revisada)
    if st.form_submit_button("Guardar cambios", type="primary"):
        errores, n_cambios = [], 0
        for foto_id, (f, cat, pie, incluir, revisada) in valores.items():
            if contar_palabras(pie) > MAX_PALABRAS:
                errores.append(f"{f['nombre']}: el pie excede {MAX_PALABRAS} palabras; no se guardó")
                continue
            cambios = actualizar_fotografia(
                p, foto_id, categoria=None if cat == SIN_CLASIFICAR else cat, pie=pie.strip() or None,
                incluir=int(incluir), revisada=int(revisada))
            n_cambios += bool(cambios)
        for e in errores:
            st.error(e)
        st.success(f"{n_cambios} fotografía(s) actualizadas.")
        st.rerun()
