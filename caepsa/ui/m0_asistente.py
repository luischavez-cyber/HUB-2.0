"""Asistente de IA: punto de entrada conversacional a todas las herramientas."""
import json
import os
import re

import anthropic
import streamlit as st

from caepsa.asistente.agente import Asistente, Evento
from caepsa.asistente.herramientas import Contexto
from caepsa.fotografia.registro import registrar_fotografia
from caepsa.ui.comun import proyecto_activo, usuario

st.title("Asistente CAEPSA")
st.caption("Pídale lo que necesite: crear o actualizar el proyecto, extraer el PDF del laboratorio, "
           "evaluar contra la NOM-138, clasificar fotografías, revisar el borrador del informe como "
           "lo haría la autoridad, revisar alertas o exportar tablas.")

if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
    st.warning("Configure la variable de entorno `ANTHROPIC_API_KEY` antes de iniciar la aplicación "
               "para habilitar el asistente. Los módulos 1–3 funcionan sin ella.")
    st.stop()

if "asistente" not in st.session_state:
    st.session_state["asistente"] = Asistente(Contexto())
    st.session_state["chat"] = []
asistente: Asistente = st.session_state["asistente"]
ctx = asistente.ctx
ctx.usuario = usuario()
ctx.proyecto = st.session_state.get("proyecto")

with st.sidebar:
    if st.button("Nueva conversación"):
        for k in ("asistente", "chat"):
            st.session_state.pop(k, None)
        st.rerun()


def mostrar_herramienta(d: dict) -> None:
    icono = "⚠️" if d["error"] else "🔧"
    with st.expander(f"{icono} {d['nombre']}", expanded=False):
        st.code(json.dumps(d["entrada"], ensure_ascii=False, indent=1), language="json")
        salida = d["salida"]
        st.code(salida if len(salida) < 6000 else salida[:6000] + "\n…", language="json")


def mostrar_archivos(rutas: list[str]) -> None:
    for ruta in rutas:
        with open(ruta, "rb") as f:
            st.download_button(f"Descargar {os.path.basename(ruta)}", f.read(), os.path.basename(ruta),
                               key=f"dl-{ruta}-{len(st.session_state['chat'])}")


for msg in st.session_state["chat"]:
    with st.chat_message(msg["rol"]):
        for d in msg.get("herramientas", []):
            mostrar_herramienta(d)
        if msg.get("texto"):
            st.markdown(msg["texto"])
        mostrar_archivos(msg.get("archivos", []))

entrada = st.chat_input("Escriba su solicitud o adjunte PDF de laboratorio, borrador del informe o fotografías",
                        accept_file="multiple", file_type=["pdf", "docx", "jpg", "jpeg", "png"])
if entrada:
    texto = entrada.text or ""
    adjuntos = []
    if entrada.files:
        p = proyecto_activo()
        if p is None:
            st.error("Seleccione o cree un proyecto antes de adjuntar archivos.")
            st.stop()
        for f in entrada.files:
            nombre = f.name.lower()
            if nombre.endswith((".pdf", ".docx")):
                es_borrador = nombre.endswith(".docx") or re.search(r"informe|borrador|caracteriz", nombre)
                tipo = "borrador" if es_borrador else "laboratorio"
                p.guardar_documento(tipo, f.name, f.getvalue())
                doc_id = p.documentos(tipo)[0]["id"]
                desc = "Borrador del informe" if es_borrador else "PDF de laboratorio"
                adjuntos.append(f"[{desc} guardado: documento_id={doc_id}, '{f.name}', tipo={tipo}]")
            else:
                foto_id = registrar_fotografia(p, f.name, f.getvalue())
                adjuntos.append(f"[Fotografía registrada: id={foto_id}, '{f.name}']")
        texto = "\n".join(adjuntos + [texto or "Procese el archivo adjunto."])
    st.session_state["chat"].append({"rol": "user", "texto": texto})
    with st.chat_message("user"):
        st.markdown(texto)

    with st.chat_message("assistant"):
        vista = {"rol": "assistant", "herramientas": [], "texto": "", "archivos": []}
        estado = st.status("Trabajando…", expanded=True)

        def al_evento(e: Evento) -> None:
            if e.tipo == "herramienta":
                vista["herramientas"].append(e.datos)
                estado.write(f"🔧 {e.datos['nombre']}" + (" (error)" if e.datos["error"] else ""))
            elif e.tipo == "aviso":
                estado.write(f"⚠️ {e.datos['texto']}")

        n_archivos = len(ctx.archivos_generados)
        try:
            vista["texto"] = asistente.enviar(texto, al_evento)
            estado.update(label="Listo", state="complete", expanded=False)
        except anthropic.APIError as exc:  # se muestra sin perder la conversación
            estado.update(label="Error", state="error")
            vista["texto"] = f"**Error al consultar el modelo:** {exc}"
        vista["archivos"] = [str(r) for r in ctx.archivos_generados[n_archivos:]]
        for d in vista["herramientas"]:
            mostrar_herramienta(d)
        st.markdown(vista["texto"])
        mostrar_archivos(vista["archivos"])
        st.session_state["chat"].append(vista)

    if ctx.proyecto != st.session_state.get("proyecto"):
        st.session_state["_cambiar_proyecto"] = ctx.proyecto
        st.rerun()
