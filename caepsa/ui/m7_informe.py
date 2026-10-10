"""Módulo 7 — Generación del Informe de Caracterización (pantalla)."""
from collections import Counter
from pathlib import Path

import streamlit as st

from caepsa.informe.generador import CAPITULOS, generar_y_registrar, verificacion_previa
from caepsa.revision.registro import listar_revisiones
from caepsa.ui.comun import requiere_proyecto

ICONO = {"ok": "✅", "aviso": "⚠️", "falta": "⛔"}
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

p = requiere_proyecto()
st.title("Generación del Informe de Caracterización")
st.caption("Consolida los módulos 1 a 6 en el informe completo en Word. Lo que no esté sustentado por datos se "
           "inserta como [COMPLETAR: …] resaltado; nunca se inventa.")

st.markdown("#### Verificación previa")
for x in verificacion_previa(p):
    st.markdown(f"{ICONO[x['nivel']]} {x['texto']}")

st.markdown("#### Formato")
with st.expander("Plantilla Word de CAEPSA (opcional)"):
    st.caption("Suba un .docx con la portada, encabezados, pies, logotipo y estilos institucionales. Se conservan "
               "sus estilos, encabezado y pie; su contenido se sustituye por el informe.")
    archivo = st.file_uploader("Plantilla (.docx)", type=["docx"])
    if archivo and st.button("Guardar plantilla"):
        p.guardar_documento("plantilla_word", archivo.name, archivo.getvalue())
        st.rerun()
plantillas = p.documentos("plantilla_word")
opciones = [None, *[d["id"] for d in plantillas]]
nombres = {d["id"]: d["nombre"] for d in plantillas}
plantilla_id = st.selectbox("Formato", opciones, format_func=lambda i: "Formato estándar" if i is None else nombres[i])
revisar = st.checkbox("Aplicar la revisión técnica automática (Módulo 5) al informe generado", value=True)

with st.expander("Estructura del informe"):
    st.markdown("Portada · Índice · " + " · ".join(CAPITULOS))

if st.button("Generar Informe de Caracterización", type="primary"):
    with st.spinner("Generando el informe…"):
        st.session_state["ultimo_informe"] = generar_y_registrar(p, plantilla_id=plantilla_id, revisar=revisar)

r = st.session_state.get("ultimo_informe")
if r and Path(r["ruta"]).exists():
    st.success(f"Informe generado: {r['nombre']}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Datos por completar", len(r["pendientes"]))
    c2.metric("Fotografías incluidas", r["fotografias"])
    if "ict" in r:
        c3.metric("ICT del informe generado", f"{r['ict']:.0f} / 100")
        st.caption(f"Dictamen interno: {r['interpretacion']}. Detalle en «5 · Revisión Técnica».")
    for a in r["avisos"]:
        st.warning(a)
    st.download_button("📄 Descargar informe (Word)", Path(r["ruta"]).read_bytes(), r["nombre"], DOCX)
    if r["pendientes"]:
        with st.expander(f"Datos por completar ({len(r['pendientes'])})"):
            for texto, n in Counter(r["pendientes"]).most_common():
                st.markdown(f"- {texto}" + (f" ×{n}" if n > 1 else ""))
    st.caption("Al abrir el archivo, Word pedirá actualizar los campos: acepte para completar el índice y la "
               "paginación.")

generados = [d for d in p.documentos("borrador") if d["nombre"].startswith("Informe_caracterizacion_")]
if generados:
    st.markdown("#### Informes generados")
    ict = {r["documento_id"]: r["ict_vigente"] for r in reversed(listar_revisiones(p))}
    for d in generados:
        c1, c2 = st.columns([4, 1])
        c1.markdown(f"**{d['nombre']}** · {d['cargado']}"
                    + (f" · ICT {ict[d['id']]:.0f}" if d["id"] in ict else ""))
        if Path(d["ruta"]).exists():
            c2.download_button("Descargar", Path(d["ruta"]).read_bytes(), d["nombre"], DOCX, key=f"dl{d['id']}")
