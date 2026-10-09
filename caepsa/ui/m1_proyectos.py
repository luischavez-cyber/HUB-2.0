"""Módulo 1 — Gestión de Proyectos (pantalla)."""
import pandas as pd
import streamlit as st

from caepsa.normativa.nom138 import PRODUCTOS, UsoSuelo
from caepsa.proyectos import CAMPOS_FICHA, Proyecto
from caepsa.tablero import MODULOS, estado
from caepsa.ui.comun import proyecto_activo, usuario

st.title("Gestión de Proyectos")

with st.expander("➕ Nuevo proyecto", expanded=not Proyecto.listar()):
    with st.form("nuevo"):
        nombre = st.text_input("Nombre del proyecto",
                               placeholder="Caracterización Km 176+500 Autopista Siglo XXI, Nueva Italia")
        cliente = st.text_input("Cliente")
        if st.form_submit_button("Crear proyecto", type="primary") and nombre.strip():
            p = Proyecto.crear(nombre.strip(), usuario=usuario(), cliente=cliente.strip())
            st.session_state["_cambiar_proyecto"] = p.clave
            st.rerun()

p = proyecto_activo()
if p is None:
    st.info("Cree un proyecto para comenzar.")
    st.stop()

ficha = p.ficha()
tab_tablero, tab_ficha, tab_docs, tab_versiones, tab_bitacora = st.tabs(
    ["Tablero", "Ficha del proyecto", "Documentos", "Versiones", "Bitácora"])

with tab_tablero:
    st.subheader(ficha.get("nombre", p.clave))
    st.caption(f"Expediente: {ficha.get('expediente') or '—'} · Cliente: {ficha.get('cliente') or '—'} · "
               f"Espacio de trabajo: `{p.ruta}`")
    conteo = p.conteos()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Puntos de muestreo", conteo["puntos"], help=f"Esperados: {ficha.get('puntos_esperados') or '—'}")
    c2.metric("Muestras", conteo["muestras"], help=f"Esperadas: {ficha.get('muestras_esperadas') or '—'}")
    c3.metric("Resultados analíticos", conteo["resultados"])
    c4.metric("Documentos", conteo["documentos"])

    avance, alertas = estado(p)
    st.markdown("#### Avance por módulo")
    for n, nombre in MODULOS:
        st.progress(min(avance[n], 1.0), text=f"{n}. {nombre} — {avance[n] * 100:.0f} %")
    st.markdown("#### Alertas pendientes")
    icono = {"alta": "🔴", "media": "🟠", "info": "⚪"}
    for a in alertas:
        st.markdown(f"{icono[a.nivel]} **M{a.modulo}** · {a.mensaje}")
    if not alertas:
        st.success("Sin alertas pendientes.")

with tab_ficha:
    with st.form("ficha"):
        valores: dict = {}
        cols = st.columns(2)
        for i, campo in enumerate(CAMPOS_FICHA):
            col = cols[i % 2]
            etiqueta = campo.etiqueta + (" *" if campo.requerido else "")
            actual = ficha.get(campo.clave)
            if campo.clave == "producto":
                opciones = ["", *PRODUCTOS]
                valores[campo.clave] = col.selectbox(
                    etiqueta, opciones, index=opciones.index(actual) if actual in opciones else 0,
                    help="Determina los parámetros que deben analizarse (NOM-138, Tabla 1)") or None
            elif campo.clave == "usos_suelo":
                valores[campo.clave] = col.multiselect(
                    etiqueta, [u.value for u in UsoSuelo], default=actual or [],
                    format_func=lambda v: UsoSuelo(v).etiqueta,
                    help="Si selecciona más de uno (uso mixto) se aplica el LMP más estricto")
            else:
                valores[campo.clave] = col.text_input(etiqueta, value=actual or "")
        if st.form_submit_button("Guardar ficha", type="primary"):
            p.actualizar_ficha({k: (v.strip() if isinstance(v, str) else v) for k, v in valores.items()})
            st.success("Ficha guardada; los demás módulos ya usan estos datos.")
            st.rerun()

with tab_docs:
    docs = p.documentos()
    if docs:
        st.dataframe(pd.DataFrame(docs)[["tipo", "nombre", "cargado", "sha256"]], hide_index=True,
                     width="stretch")
    else:
        st.caption("Sin documentos. El PDF de laboratorio se carga en el Módulo 2.")

with tab_versiones:
    etiqueta = st.text_input("Etiqueta de la versión", placeholder="Ej. Resultados validados por responsable técnico")
    if st.button("Crear instantánea") and etiqueta.strip():
        st.success(f"Versión guardada: {p.crear_instantanea(etiqueta.strip()).name}")
    versiones = p.versiones()
    if versiones:
        elegida = st.selectbox("Versiones guardadas", versiones, format_func=lambda v: v.name)
        if st.button("Restaurar versión seleccionada",
                     help="Antes de restaurar se guarda automáticamente una copia del estado actual"):
            p.restaurar_instantanea(elegida)
            st.success("Versión restaurada.")
            st.rerun()

with tab_bitacora:
    registros = p.bitacora()
    if registros:
        st.dataframe(pd.DataFrame(registros), hide_index=True, width="stretch")
    else:
        st.caption("Sin cambios registrados.")
