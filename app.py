"""HUB CAEPSA — Plataforma de auditoría de informes de caracterización (NOM-138-SEMARNAT/SSA1-2012).

Ejecutar con:  streamlit run app.py
"""
import streamlit as st

from caepsa.proyectos import Proyecto

st.set_page_config(page_title="HUB CAEPSA", page_icon="🧪", layout="wide")

with st.sidebar:
    st.markdown("### HUB CAEPSA")
    st.caption("Consultoría Ambiental Estudios y Proyectos S.A. de C.V.")
    st.text_input("Usuario", key="usuario", placeholder="Nombre de quien captura")
    proyectos = Proyecto.listar()
    claves = [p["clave"] for p in proyectos]
    nombres = {p["clave"]: p["nombre"] for p in proyectos}
    if "_cambiar_proyecto" in st.session_state:  # cambio solicitado por otra página o el asistente
        st.session_state["proyecto"] = st.session_state.pop("_cambiar_proyecto")
    if claves:
        if st.session_state.get("proyecto") not in claves:
            st.session_state["proyecto"] = claves[0]
        st.selectbox("Proyecto activo", claves, format_func=lambda c: nombres.get(c, c), key="proyecto")

paginas = st.navigation([
    st.Page("caepsa/ui/m0_asistente.py", title="Asistente IA", icon="💬", default=True),
    st.Page("caepsa/ui/m1_proyectos.py", title="1 · Gestión de Proyectos", icon="📁"),
    st.Page("caepsa/ui/m2_laboratorio.py", title="2 · Resultados de Laboratorio", icon="🧾"),
    st.Page("caepsa/ui/m3_evaluacion.py", title="3 · Evaluación NOM-138", icon="⚖️"),
    st.Page("caepsa/ui/m4_fotografias.py", title="4 · Gestión Fotográfica", icon="📷"),
])
paginas.run()
