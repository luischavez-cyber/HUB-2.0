"""Módulo 2 — Extracción de Resultados de Laboratorio (pantalla)."""
import pandas as pd
import streamlit as st

from caepsa.laboratorio.captura import COLUMNAS_PLANTILLA, guardar_extraccion, importar_csv, importar_filas, plantilla_csv
from caepsa.laboratorio.extractor import extraer
from caepsa.normativa.nom138 import PARAMETROS
from caepsa.ui.comun import requiere_proyecto

p = requiere_proyecto()
ficha = p.ficha()
st.title("Resultados de Laboratorio")
st.caption(f"Proyecto: {ficha.get('nombre', p.clave)} · Laboratorio: {ficha.get('laboratorio') or '—'}")

tab_pdf, tab_datos, tab_csv = st.tabs(["Extraer de PDF", "Revisar y capturar", "Importar CSV"])

with tab_pdf:
    archivo = st.file_uploader("PDF oficial del laboratorio acreditado", type=["pdf"])
    if archivo is not None:
        contenido = archivo.getvalue()
        ext = extraer(contenido)
        st.session_state["extraccion"] = (archivo.name, contenido, ext)
    if "extraccion" in st.session_state:
        nombre, contenido, ext = st.session_state["extraccion"]
        for a in ext.advertencias:
            st.warning(a)
        st.write(f"**{nombre}** — {ext.paginas} página(s), {len(ext.muestras)} muestra(s) identificada(s), "
                 f"{sum(len(m.resultados) for m in ext.muestras)} resultado(s).")
        if ext.muestras:
            resumen = pd.DataFrame([{
                "Muestra": m.clave, "Página": m.pagina, "Punto": m.punto, "Zona": m.zona,
                "Profundidad (m)": m.profundidad_m, "X UTM": m.utm_x, "Y UTM": m.utm_y,
                "Fecha muestreo": m.fecha_muestreo,
                "Parámetros": ", ".join(PARAMETROS[k].clave for k in m.resultados),
                "Campos por capturar": ", ".join(m.faltantes),
            } for m in ext.muestras])
            st.dataframe(resumen.style.map(lambda v: "background-color:#fff3cd" if v else "",
                                           subset=["Campos por capturar"]),
                         hide_index=True, width="stretch")
            if ext.metodos:
                st.caption("Métodos analíticos detectados: " +
                           "; ".join(f"{PARAMETROS[k].nombre}: {v}" for k, v in ext.metodos.items()))
            if st.button("Guardar en el proyecto", type="primary"):
                p.guardar_documento("laboratorio", nombre, contenido)
                n = guardar_extraccion(p, ext, utm_zona=ficha.get("utm_zona"))
                st.success(f"{n} resultado(s) guardados. Complete los campos faltantes en «Revisar y capturar».")
                del st.session_state["extraccion"]
        with st.expander("Texto extraído (para verificación)"):
            pagina = st.number_input("Página", 1, max(ext.paginas, 1), 1)
            st.text(ext.texto[pagina - 1] if ext.texto else "")

with tab_datos:
    st.markdown("Edite o complete cualquier campo. Cada cambio queda registrado en la bitácora del proyecto.")
    filas = p.tabla_resultados()
    df = pd.DataFrame(filas, columns=list(COLUMNAS_PLANTILLA) + ["origen"])
    if df.empty:
        df = pd.DataFrame(columns=list(COLUMNAS_PLANTILLA))
    df["menor_que"] = df["menor_que"].fillna(0).astype(bool)
    zonas = p.zonas()
    editado = st.data_editor(
        df[list(COLUMNAS_PLANTILLA)], num_rows="dynamic", width="stretch", hide_index=True,
        column_config={
            "zona": st.column_config.SelectboxColumn("zona", options=zonas),
            "parametro": st.column_config.SelectboxColumn("parametro", options=list(PARAMETROS)),
            "menor_que": st.column_config.CheckboxColumn("< LD"),
            "utm_x": st.column_config.NumberColumn("utm_x", format="%.2f"),
            "utm_y": st.column_config.NumberColumn("utm_y", format="%.2f"),
        },
        key="editor_resultados",
    )
    if st.button("Guardar cambios", type="primary"):
        registros = editado.astype(object).where(editado.notna(), None).to_dict("records")
        errores = importar_filas(p, registros, origen="manual")
        for e in errores:
            st.error(e)
        if not errores:
            st.success("Cambios guardados.")
            st.rerun()
    with st.expander("Eliminar muestra"):
        muestras = sorted({f["muestra"] for f in filas})
        if muestras:
            m = st.selectbox("Muestra", muestras)
            if st.button("Eliminar", help="Elimina la muestra y sus resultados (queda en bitácora)"):
                p.eliminar_muestra(m)
                st.rerun()

with tab_csv:
    st.download_button("Descargar plantilla CSV", plantilla_csv(), "plantilla_resultados.csv", "text/csv")
    st.caption("Una fila por resultado. `parametro` acepta la clave (HFL, BENCENO, …) o el nombre del analito. "
               "`valor` admite `<0.5` para resultados menores al límite de detección.")
    csv = st.file_uploader("CSV de resultados", type=["csv"])
    if csv is not None and st.button("Importar CSV", type="primary"):
        errores = importar_csv(p, csv.getvalue())
        for e in errores:
            st.error(e)
        st.success("Importación terminada." if not errores else "Importación terminada con errores.")
