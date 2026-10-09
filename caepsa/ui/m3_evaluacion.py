"""Módulo 3 — Evaluación Normativa NOM-138-SEMARNAT/SSA1-2012 (pantalla)."""
import pandas as pd
import streamlit as st

from caepsa.exportacion.tablas import a_excel, a_word, matriz, parametros_presentes
from caepsa.normativa.evaluacion import CUMPLE, EXCEDE, INDETERMINADO, NO_DETECTADO, evaluar, resumen
from caepsa.normativa.nom138 import NORMA, PARAMETROS, REFERENCIAS, UNIDAD, lmp_aplicable, parametros_requeridos
from caepsa.ui.comun import requiere_proyecto

p = requiere_proyecto()
ficha = p.ficha()
st.title("Evaluación Normativa")
st.caption(f"{NORMA} · Unidades: {UNIDAD}")

usos = p.usos_suelo()
if not usos:
    st.error("Defina el uso de suelo en la ficha del proyecto (Módulo 1); es necesario para elegir el LMP.")
    st.stop()
filas = p.tabla_resultados()
if not any(f["parametro"] for f in filas):
    st.info("No hay resultados de laboratorio. Cárguelos en el Módulo 2.")
    st.stop()

producto = ficha.get("producto")
muestras = evaluar(filas, usos, producto)
s = resumen(muestras)

st.markdown(f"**Uso de suelo:** {' / '.join(u.etiqueta for u in usos)}" +
            (" — *uso mixto: se aplica el LMP más estricto*" if len(usos) > 1 else ""))
if producto:
    st.markdown(f"**Producto:** {producto} → parámetros requeridos ({REFERENCIAS['parametros_por_producto']}): " +
                ", ".join(PARAMETROS[c].nombre for c in parametros_requeridos(producto)))
else:
    st.warning("Sin tipo de contaminante en la ficha: no se verifica la Tabla 1 (parámetros requeridos).")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Muestras", s["muestras"])
c2.metric("Puntos", s["puntos"])
c3.metric("Exceden LMP", s["por_estado"].get(EXCEDE, 0))
c4.metric("Cumplen", s["por_estado"].get(CUMPLE, 0))
c5.metric("Indeterminadas", s["por_estado"].get(INDETERMINADO, 0))
if s["puntos_con_excedencia"]:
    st.error("Puntos con excedencia: " + ", ".join(s["puntos_con_excedencia"]))
if s["excedencias_por_parametro"]:
    st.markdown("**Excedencias por parámetro:** " + " · ".join(
        f"{PARAMETROS[k].nombre}: {n} (máx. {s['maximos'][k]:,.2f} vs LMP {lmp_aplicable(k, usos):g})"
        for k, n in s["excedencias_por_parametro"].items()))

f1, f2 = st.columns(2)
zonas = sorted({m.zona for m in muestras if m.zona})
sel_zonas = f1.multiselect("Zona", zonas, default=zonas)
sel_estados = f2.multiselect("Estado de cumplimiento", [EXCEDE, CUMPLE, INDETERMINADO, "Sin dato"],
                             default=[EXCEDE, CUMPLE, INDETERMINADO, "Sin dato"])
filtradas = [m for m in muestras if (m.zona in sel_zonas or not m.zona) and m.estado in sel_estados]

enc, valores, estados = matriz(filtradas)
params = parametros_presentes(muestras)
if filtradas:
    df = pd.DataFrame(valores, columns=enc)
    colores = {EXCEDE: "background-color:#f8d7da;color:#9c0006;font-weight:700",
               INDETERMINADO: "background-color:#fff3cd", CUMPLE: "", NO_DETECTADO: ""}
    estilos = pd.DataFrame([[colores.get(e or "", "") for e in fila] for fila in estados], columns=enc)
    # Dictamen siempre coloreado; HFL con borde adicional por ser el parámetro crítico del sitio.
    estilos["Dictamen"] = [colores.get(e, "") or "background-color:#d4edda" for e in df["Dictamen"]]
    if "Fracción ligera" in df.columns:
        estilos["Fracción ligera"] = [x + ";border:2px solid #9c0006" if "f8d7da" in x else x
                                      for x in estilos["Fracción ligera"]]
    lmp = pd.DataFrame([["", "", "LMP", "", "", "", *[f"{lmp_aplicable(c, usos):g}" for c in params], ""]],
                       columns=enc)
    # Todo como texto: columnas homogéneas para la tabla (UTM sin separador de miles).
    for col in ("X (UTM)", "Y (UTM)"):
        df[col] = [f"{v:.2f}" if isinstance(v, (int, float)) else "" for v in df[col]]
    st.dataframe(pd.concat([lmp, df], ignore_index=True).astype(str).style.apply(
        lambda _: pd.concat([pd.DataFrame([[""] * len(enc)], columns=enc), estilos], ignore_index=True), axis=None),
        hide_index=True, width="stretch", height=min(38 * (len(df) + 2), 900))
else:
    st.caption("Ningún registro coincide con los filtros.")

with st.expander("Detalle por resultado (trazabilidad)"):
    det = [{"Muestra": m.muestra, "Parámetro": r.parametro, "Valor": r.valor, "<LD": r.menor_que,
            "LD": r.limite_deteccion, "LMP": r.lmp,
            "Valor/LMP": round(r.proporcion, 2) if r.proporcion is not None else None,
            "Estado": r.estado, "Método": r.datos.get("metodo"), "Página PDF": r.datos.get("pagina_pdf"),
            "Referencia": r.referencia, "Observaciones": "; ".join(r.observaciones)}
           for m in filtradas for r in m.resultados]
    st.dataframe(pd.DataFrame(det), hide_index=True, width="stretch")
    faltantes = [(m.muestra, ", ".join(PARAMETROS[c].nombre for c in m.faltantes)) for m in filtradas if m.faltantes]
    if faltantes:
        st.warning("Parámetros exigidos por la Tabla 1 no reportados:\n\n" +
                   "\n".join(f"- {mu}: {fa}" for mu, fa in faltantes))

e1, e2 = st.columns(2)
e1.download_button("Exportar a Excel", a_excel(filtradas, usos, ficha), f"{p.clave}_NOM138.xlsx",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
e2.download_button("Tabla para informe (Word)", a_word(filtradas, usos, ficha), f"{p.clave}_tabla_NOM138.docx",
                   "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
st.caption("Referencias: " + " · ".join(REFERENCIAS.values()))
