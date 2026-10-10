"""Módulo 6 — Análisis de Dispersión de Hidrocarburos (pantalla)."""
import os
import re

import anthropic
import pandas as pd
import streamlit as st

from caepsa.dispersion import capitulo as cap
from caepsa.dispersion import medio_fisico as mf
from caepsa.dispersion.analisis import analizar
from caepsa.dispersion.figura import plano
from caepsa.ui.comun import requiere_proyecto

NIVEL = {"alta": "🔴 Alta", "media": "🟡 Media", "baja": "🟢 Baja", "indeterminado": "⚪ Indeterminado"}

p = requiere_proyecto()
st.title("Análisis de Dispersión de Hidrocarburos")
st.caption("Genera el Capítulo 5 del Informe de Caracterización a partir de datos con fuente documentada")

tab_mf, tab_an, tab_cap = st.tabs(["Medio físico", "Análisis", "Capítulo 5"])

with tab_mf:
    datos = mf.leer(p)
    falt = mf.faltantes(datos)
    st.caption("Cada dato requiere su **fuente** (levantamiento de campo, carta temática, estación climatológica, "
               "informe…). Los datos sin fuente se guardan pero **no se usan** en el análisis.  \\* requerido")
    if falt["sin_valor"]:
        st.warning("Requeridos sin capturar: " + ", ".join(c.etiqueta for c in falt["sin_valor"]))
    if falt["sin_fuente"]:
        st.warning("Con valor pero sin fuente (no se usan): " + ", ".join(c.etiqueta for c in falt["sin_fuente"]))
    with st.form("medio_fisico"):
        entradas = {}
        for grupo in mf.GRUPOS:
            st.markdown(f"**{grupo}**")
            for c in (x for x in mf.CAMPOS if x.grupo == grupo):
                actual = datos.get(c.clave, {})
                c1, c2 = st.columns([1, 1])
                etiqueta = f"{c.etiqueta}{' (' + c.unidad + ')' if c.unidad else ''}{' *' if c.requerido else ''}"
                if c.tipo == "opcion":
                    opciones = ["", *c.opciones]
                    v = c1.selectbox(etiqueta, opciones, index=opciones.index(actual.get("valor") or ""),
                                     key=f"v_{c.clave}")
                else:
                    previo = actual.get("valor")
                    texto = "" if previo is None else (f"{previo:.2f}" if c.clave in ("origen_x", "origen_y")
                                                       else f"{previo:g}" if isinstance(previo, float) else str(previo))
                    v = c1.text_input(etiqueta, texto, key=f"v_{c.clave}")
                f = c2.text_input("Fuente", actual.get("fuente") or "", key=f"f_{c.clave}")
                entradas[c.clave] = {"valor": v, "fuente": f, "observacion": actual.get("observacion")}
        if st.form_submit_button("Guardar datos del medio físico", type="primary"):
            cambios = {k: d for k, d in entradas.items()
                       if (d["valor"] or d["fuente"] or k in datos)}
            try:
                n = mf.guardar(p, cambios)
                st.success(f"{len(n)} dato(s) actualizados.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

with tab_an:
    a = analizar(p)
    if not a.get("disponible"):
        st.info(a.get("motivo"))
    else:
        e, d = a["espacial"], a["delimitacion"]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Puntos con excedencia", f"{e['puntos_con_excedencia']} de {e['puntos_evaluados']}")
        m2.metric("Extensión máxima desde el origen", f"{e['extension_max_m']:g} m" if "extension_max_m" in e else "—")
        m3.metric("Área afectada (envolvente)", f"{e['area_afectada_m2']:,.0f} m²" if "area_afectada_m2" in e else "—")
        vol = e.get("volumen_estimado_m3")
        m4.metric("Volumen preliminar", f"{vol['central']:,.0f}–{vol['conservador']:,.0f} m³" if vol else "—",
                  help=vol["metodo"] if vol else "Requiere ≥ 3 puntos con excedencia y profundidades")
        if "direccion_dispersion" in e:
            c = e.get("coincidencia_pendiente")
            st.markdown(f"**Dirección de dispersión observada:** {e['direccion_dispersion']['rumbo']} "
                        f"({e['direccion_dispersion']['azimut']}°)"
                        + (f" · pendiente hacia {c['direccion_pendiente']}: **{c['valoracion']}** "
                           f"(diferencia {c['diferencia_grados']}°)" if c else ""))
        for eje in ("horizontal", "vertical"):
            if d[eje]["cerrada"]:
                st.success(f"Delimitación {eje}: cerrada")
            else:
                st.error(f"Delimitación {eje}: abierta. {d[eje]['motivo']}")
        png = plano(a)
        if png:
            st.image(png, caption="Figura 5.1. Distribución espacial de los puntos con excedencia de LMP.",
                     width=650)
        st.markdown("#### Matriz de susceptibilidad a la migración")
        st.dataframe(pd.DataFrame([{"Factor": x["factor"], "Susceptibilidad": NIVEL[x["nivel"]],
                                    "Justificación": x["justificacion"]} for x in a["matriz"]]),
                     hide_index=True, width="stretch")
        st.caption(a["criterio_tamizaje"])
        if a.get("transito_vertical"):
            t = a["transito_vertical"]
            st.info(f"Tiempo de tránsito vertical estimado al nivel freático: {t['dias']:g} días "
                    f"({t['espesor_no_saturado_m']:g} m no saturados). {t['supuesto']}")
        st.markdown("#### Afectación por punto")
        st.dataframe(pd.DataFrame([{
            "Punto": x["punto"], "Zona": x["zona"], "Muestras": x["muestras"], "Excede": "Sí" if x["excede"] else "No",
            "Prof. máx. muestreada (m)": x["prof_max_muestreada_m"],
            "Prof. máx. con excedencia (m)": x["prof_max_excedencia_m"],
            "Delimitación vertical": "Abierta" if x["vertical_abierta"] else "Cerrada"} for x in a["puntos"]]),
            hide_index=True, width="stretch")
        if a["pendientes"]:
            st.markdown("#### Información faltante")
            for x in a["pendientes"]:
                st.markdown(f"- {x}")

with tab_cap:
    hay_api = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    c1, c2 = st.columns([2, 1])
    usar_ia = c1.checkbox("Redactar con IA (cifras verificadas contra los datos)", value=hay_api, disabled=not hay_api,
                          help=None if hay_api else "Sin ANTHROPIC_API_KEY se genera la redacción base por plantilla")
    if c2.button("Generar Capítulo 5", type="primary"):
        with st.spinner("Generando el capítulo…"):
            try:
                cap.generar(p, usar_ia=usar_ia)
            except anthropic.APIError as exc:
                st.error(f"Error al consultar el modelo: {exc}")
        st.rerun()
    versiones = cap.listar(p)
    if not versiones:
        st.info("Aún no se ha generado el capítulo.")
    else:
        r = st.selectbox("Versión", versiones, format_func=lambda x: f"#{x['id']} · {x['fecha']} · "
                         + ("IA" if x["usa_ia"] else "plantilla"))
        if r["aviso"]:
            st.warning(r["aviso"])
        marcadas: dict[str, set[str]] = {}
        for c in r["cifras_no_respaldadas"]:
            marcadas.setdefault(c["seccion"], set()).add(c["cifra"])
        if marcadas:
            st.warning(f"{len(r['cifras_no_respaldadas'])} cifra(s) del texto no aparecen en los datos del proyecto; "
                       "están resaltadas aquí y en el Word para su verificación.")
        st.download_button("📄 Descargar Capítulo 5 (Word)", cap.a_word(p, r["id"]), f"{p.clave}_capitulo5_v{r['id']}.docx",
                           "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        for s in r["capitulo"]["secciones"]:
            st.markdown(f"##### {s['numero']} {s['titulo']}")
            texto = s["texto"].replace("$", "\\$")
            for cifra in sorted(marcadas.get(s["numero"], ()), key=len, reverse=True):
                texto = re.sub(rf"(?<![\w.]){re.escape(cifra)}(?![\w])", f":orange-background[{cifra}]", texto)
            st.markdown(texto)
