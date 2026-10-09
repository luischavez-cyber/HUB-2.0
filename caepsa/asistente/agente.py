"""Asistente de IA (agente con tool use) que opera todos los módulos de la plataforma."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable

import anthropic

from ..normativa.nom138 import NORMA, PUBLICACION_DOF
from .herramientas import DEFINICIONES, Contexto, ejecutar

MODELO = os.environ.get("CAEPSA_MODELO", "claude-opus-5-5")
MAX_PASOS = 25

SISTEMA = f"""Eres el asistente técnico de la plataforma HUB de Consultoría Ambiental Estudios y Proyectos \
S.A. de C.V. (CAEPSA). Ayudas al equipo a integrar, auditar y generar informes de caracterización de sitios \
contaminados por derrames de hidrocarburos en México, tomando como referencia estructural el Informe de \
Caracterización de Nueva Italia, Michoacán (Km 176+500, Autopista Siglo XXI).

Tienes herramientas que operan la plataforma: gestión de proyectos (ficha, tablero, versiones, bitácora), \
extracción de resultados de laboratorio desde PDF, captura manual y evaluación normativa. Úsalas para \
consultar y modificar datos en lugar de pedir al usuario que navegue por la interfaz.

Reglas que no se negocian:
- El marco regulatorio es exclusivamente la {NORMA} (DOF {PUBLICACION_DOF}). No cites ni apliques otras \
normas, guías o criterios (EPA, normas extranjeras, etc.) como fuente de límites. Los métodos analíticos que \
reporte el laboratorio se mencionan solo como dato del informe.
- Todo LMP, dictamen o parámetro requerido proviene de las herramientas consultar_norma y evaluar_nom138. \
No calcules ni recuerdes LMP de memoria. Cita la tabla o apartado que devuelve la herramienta.
- Nunca inventes resultados analíticos, coordenadas, profundidades, fechas ni datos del proyecto. Si un dato \
falta, dilo y pide al usuario la fuente (PDF oficial o captura). Solo registra datos que el usuario te dicte \
o que provengan del documento oficial.
- Antes de modificar la ficha o registrar resultados, resume lo que vas a guardar. Tras cambios importantes \
ofrece crear una versión.
- Si una referencia aparece marcada para cotejar contra el DOF, menciónalo.

Estilo: español técnico, preciso y breve. Usa tablas Markdown para resultados. Cuando haya excedencias, \
nómbralas con muestra, punto, zona, valor y LMP. Los módulos de gestión fotográfica, revisión técnica, \
análisis de dispersión y generación del informe completo están en desarrollo: si te los piden, explica qué \
puedes adelantar con los datos disponibles."""

# Las entradas se validan al ejecutar (argumentos inesperados -> tool_result con is_error).
HERRAMIENTAS = DEFINICIONES


@dataclass
class Evento:
    tipo: str  # "herramienta" | "texto" | "aviso"
    datos: dict[str, Any] = field(default_factory=dict)


class Asistente:
    """Conversación con el agente. ``mensajes`` es el historial completo (solo se agrega, nunca se edita)."""

    def __init__(self, ctx: Contexto, cliente: Any | None = None):
        self.ctx = ctx
        self.cliente = cliente or anthropic.Anthropic()
        self.mensajes: list[dict[str, Any]] = []

    def _contexto_turno(self) -> str:
        return f"[Contexto de la plataforma] Usuario: {self.ctx.usuario}. Proyecto activo: {self.ctx.proyecto or 'ninguno'}."

    def enviar(self, texto: str, al_evento: Callable[[Evento], None] = lambda e: None) -> str:
        self.mensajes.append({"role": "user", "content": [
            {"type": "text", "text": self._contexto_turno()},
            {"type": "text", "text": texto},
        ]})
        respuesta_final = ""
        for _ in range(MAX_PASOS):
            r = self.cliente.beta.messages.create(
                model=MODELO,
                max_tokens=16000,
                system=SISTEMA,
                tools=HERRAMIENTAS,
                messages=self.mensajes,
                output_config={"effort": "high"},
                cache_control={"type": "ephemeral"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            # Historial íntegro (incluye bloques de razonamiento) para no invalidar el contexto.
            self.mensajes.append({"role": "assistant", "content": r.content})
            textos = [b.text for b in r.content if b.type == "text"]
            if textos:
                respuesta_final = "\n\n".join(textos)
                al_evento(Evento("texto", {"texto": respuesta_final}))

            if r.stop_reason == "refusal":
                self._cerrar_llamadas_pendientes(r.content)
                al_evento(Evento("aviso", {"texto": "El modelo declinó la solicitud."}))
                return respuesta_final or "No puedo ayudar con esa solicitud."
            if r.stop_reason == "max_tokens":
                self._cerrar_llamadas_pendientes(r.content)
                al_evento(Evento("aviso", {"texto": "Respuesta truncada por longitud."}))
                return respuesta_final
            if r.stop_reason == "pause_turn":
                continue
            usos = [b for b in r.content if b.type == "tool_use"]
            if r.stop_reason != "tool_use" or not usos:
                return respuesta_final

            resultados = []
            for b in usos:
                salida, error = ejecutar(self.ctx, b.name, dict(b.input))
                al_evento(Evento("herramienta", {"nombre": b.name, "entrada": dict(b.input),
                                                 "salida": salida, "error": error}))
                resultados.append({"type": "tool_result", "tool_use_id": b.id, "content": salida,
                                   **({"is_error": True} if error else {})})
            self.mensajes.append({"role": "user", "content": resultados})
        al_evento(Evento("aviso", {"texto": f"Se alcanzó el máximo de {MAX_PASOS} pasos."}))
        return respuesta_final

    def _cerrar_llamadas_pendientes(self, contenido: list[Any]) -> None:
        """Toda llamada a herramienta necesita su resultado antes del siguiente turno."""
        pendientes = [b for b in contenido if b.type == "tool_use"]
        if pendientes:
            self.mensajes.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                 "content": "No ejecutada: la respuesta se interrumpió."} for b in pendientes]})
