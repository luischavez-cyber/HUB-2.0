"""Utilidades compartidas de la interfaz Streamlit."""
from __future__ import annotations

import streamlit as st

from ..proyectos import Proyecto


def usuario() -> str:
    return st.session_state.get("usuario") or "sin identificar"


def proyecto_activo() -> Proyecto | None:
    clave = st.session_state.get("proyecto")
    if not clave:
        return None
    try:
        return Proyecto.abrir(clave, usuario())
    except KeyError:
        st.session_state.pop("proyecto", None)
        return None


def requiere_proyecto() -> Proyecto:
    p = proyecto_activo()
    if p is None:
        st.info("Seleccione o cree un proyecto en **Módulo 1 — Gestión de Proyectos**.")
        st.stop()
    return p
