"""Módulo 5 — Revisión Técnica Ambiental (pantalla)."""
import os

import anthropic
import pandas as pd
import streamlit as st

from caepsa.revision import dictamen
from caepsa.revision.indice import CATEGORIAS, DIMENSIONES, ETIQUETA_CRITICIDAD, calcular_ict
from caepsa.revision.registro import ESTADOS, actualizar_hallazgo, hallazgos_de, listar_revisiones, revisar_borrador
from caepsa.ui.comun import requiere_proyecto

ICONO = {"critica": "🔴", "alta": "🟠", "media": "🟡", "baja": "🟢", "info": "⚪"}

p = requiere_proyecto()
st.title("Revisión Técnica Ambiental")
st.caption("Revisión del borrador desde la perspectiva de SEMARNAT / ASEA · Marco normativo: NOM-138-SEMARNAT/SSA1-2012")

with st.expander("➕ Cargar borrador del informe", expanded=not p.documentos("borrador")):
    archivo = st.file_uploader("Borrador (.docx o .pdf)", type=["docx", "pdf"])
    if archivo and st.button("Guardar borrador", type="primary"):
        p.guardar_documento("borrador", archivo.name, archivo.getvalue())
        st.success("Borrador guardado.")
        st.rerun()

borradores = p.documentos("borrador")
if not borradores:
    st.info("Cargue el borrador del informe para revisarlo.")
    st.stop()

hay_api = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
c1, c2, c3 = st.columns([3, 2, 1])
doc = c1.selectbox("Borrador", borradores, format_func=lambda d: f"{d['nombre']} · {d['cargado']}")
usar_ia = c2.checkbox("Incluir revisión completa con IA", value=hay_api, disabled=not hay_api,
                      help=None if hay_api else "Configure ANTHROPIC_API_KEY; sin ella solo corren las "
                                                "verificaciones automáticas")
if c3.button("Revisar", type="primary"):
    with st.spinner("Revisando el borrador… (la revisión con IA puede tardar varios minutos)"):
        try:
            revisar_borrador(p, doc["id"], usar_ia=usar_ia)
        except anthropic.APIError as exc:
            st.error(f"Error al consultar el modelo: {exc}")
        except ValueError as exc:
            st.error(str(exc))
    st.rerun()

revisiones = listar_revisiones(p)
if not revisiones:
    st.info("Aún no hay revisiones. Seleccione el borrador y pulse «Revisar».")
    st.stop()

with st.expander(f"Historial de revisiones ({len(revisiones)})"):
    st.dataframe(pd.DataFrame([{
        "ID": r["id"], "Fecha": r["fecha"], "Documento": r["documento"], "ICT original": r["ict"],
        "ICT vigente": r["ict_vigente"], "Con IA": "Sí" if r["usa_ia"] else "No", "Revisó": r["usuario"],
    } for r in revisiones]), hide_index=True, width="stretch")

rev = st.selectbox("Revisión", revisiones, format_func=lambda r: f"#{r['id']} · {r['documento']} · {r['fecha']}")
hallazgos = hallazgos_de(p, rev["id"])
ict = calcular_ict(hallazgos)
indice = revisiones.index(rev)
previa = revisiones[indice + 1] if indice + 1 < len(revisiones) else None

m0, *ms = st.columns(1 + len(DIMENSIONES))
m0.metric("Índice de Calidad Técnica", f"{ict['ict']:.0f} / 100",
          delta=f"{ict['ict'] - previa['ict_vigente']:+.0f} vs revisión #{previa['id']}" if previa else None)
for col, (d, (nombre, peso)) in zip(ms, DIMENSIONES.items()):
    col.metric(f"{nombre} ({peso * 100:.0f} %)", f"{ict['subindices'][d]:.0f}")
st.markdown(f"**Dictamen interno:** {ict['interpretacion']}")
st.caption(dictamen.AVISO)
if rev["aviso"]:
    st.warning(rev["aviso"])
if rev["resumen"]:
    st.markdown("#### Síntesis de la revisión")
    st.write(rev["resumen"])
if rev["fortalezas"]:
    st.markdown("**Fortalezas:** " + " · ".join(rev["fortalezas"]))

st.markdown("#### Hallazgos")
f1, f2, f3, f4 = st.columns(4)
crit_sel = f1.multiselect("Criticidad", list(ETIQUETA_CRITICIDAD), default=list(ETIQUETA_CRITICIDAD),
                          format_func=lambda c: f"{ICONO[c]} {ETIQUETA_CRITICIDAD[c]}")
cat_sel = f2.multiselect("Categoría", list(CATEGORIAS), default=list(CATEGORIAS),
                         format_func=lambda c: CATEGORIAS[c][0])
origen_sel = f3.multiselect("Origen", ["automatica", "ia"], default=["automatica", "ia"],
                            format_func=lambda o: "Verificación automática" if o == "automatica" else "Revisión IA")
estado_sel = f4.multiselect("Estado", list(ESTADOS), default=["abierto", "atendido"])
visibles = [h for h in hallazgos if h.criticidad in crit_sel and h.categoria in cat_sel and h.origen in origen_sel
            and h.estado in estado_sel]
st.caption(" · ".join(f"{ICONO[c]} {ETIQUETA_CRITICIDAD[c]}: {sum(1 for h in hallazgos if h.criticidad == c)}"
                      for c in ETIQUETA_CRITICIDAD))

if visibles:
    df = pd.DataFrame([{
        "id": h.id, "Criticidad": f"{ICONO[h.criticidad]} {ETIQUETA_CRITICIDAD[h.criticidad]}",
        "Categoría": CATEGORIAS[h.categoria][0], "Ubicación": h.ubicacion, "Hallazgo": h.descripcion,
        "Evidencia": (h.evidencia + (" ⚠️ cita no localizada" if h.evidencia_localizada is False else "")),
        "Recomendación": h.recomendacion, "Referencia": h.referencia,
        "Origen": "IA" if h.origen == "ia" else "Automática", "Estado": h.estado, "Nota": h.nota,
    } for h in visibles])
    editado = st.data_editor(
        df, hide_index=True, width="stretch", key=f"hallazgos{rev['id']}",
        disabled=[c for c in df.columns if c not in ("Estado", "Nota")],
        column_config={"id": None, "Estado": st.column_config.SelectboxColumn("Estado", options=list(ESTADOS)),
                       "Hallazgo": st.column_config.TextColumn(width="large"),
                       "Recomendación": st.column_config.TextColumn(width="large")})
    if st.button("Guardar estados"):
        errores = []
        for (_, a), (_, b) in zip(df.iterrows(), editado.iterrows()):
            if (a["Estado"], a["Nota"]) != (b["Estado"], b["Nota"] or ""):
                try:
                    actualizar_hallazgo(p, int(a["id"]), b["Estado"], b["Nota"] or "")
                except ValueError as e:
                    errores.append(f"Hallazgo {a['id']}: {e}")
        for e in errores:
            st.error(e)
        if not errores:
            st.rerun()
else:
    st.caption("Ningún hallazgo coincide con los filtros.")

e1, e2 = st.columns(2)
e1.download_button("📄 Dictamen de revisión (Word)", dictamen.a_word(p, rev["id"]),
                   f"{p.clave}_revision{rev['id']}_dictamen.docx",
                   "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
e2.download_button("📊 Matriz de hallazgos (Excel)", dictamen.a_excel(p, rev["id"]),
                   f"{p.clave}_revision{rev['id']}_hallazgos.xlsx",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
