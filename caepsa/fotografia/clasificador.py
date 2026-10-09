"""Módulo 4 — Clasificación de fotografías y pies de foto técnicos con Claude Vision."""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any

import anthropic

from .metadatos import preparar_imagen

MODELO = os.environ.get("CAEPSA_MODELO", "claude-opus-5-5")
MAX_PALABRAS = 15

# Orden en que aparecen en la sección fotográfica del informe.
CATEGORIAS: dict[str, tuple[str, str]] = {
    "reconocimiento": ("Reconocimiento del sitio",
                       "vistas generales, accesos, área afectada por el derrame, vegetación, infraestructura, señalización"),
    "muestreo": ("Muestreo de suelo",
                 "toma de muestras, herramientas, medición de profundidad, frascos, etiquetado, preservación"),
    "excavaciones": ("Excavaciones y sondeos", "calas, zanjas, perfiles de suelo, perforaciones o sondeos manuales"),
    "pozos": ("Pozos de monitoreo", "perforación, instalación de ademe, brocal, purga, medición de nivel"),
    "laboratorio": ("Evidencias de laboratorio y cadena de custodia",
                    "hieleras, cadena de custodia, embalaje, entrega o recepción en laboratorio"),
    "cierre": ("Cierre de actividades", "limpieza, retiro de materiales o residuos, relleno, condición final del sitio"),
    "otros": ("Otras evidencias", "fotografías que no corresponden a ninguna de las categorías anteriores"),
}

SISTEMA = f"""Eres especialista en documentación fotográfica de estudios de caracterización de suelos \
contaminados por hidrocarburos en México. Clasificas cada fotografía en una categoría y redactas su pie de foto \
técnico para el informe.

Categorías:
{chr(10).join(f'- {k}: {v[0]} ({v[1]})' for k, v in CATEGORIAS.items())}

Reglas del pie de foto (deben ser consistentes en todo el informe):
- Una sola oración de máximo {MAX_PALABRAS} palabras, en español, sin punto final.
- Inicia con el sustantivo de la actividad u objeto: «Vista general…», «Toma de muestra…», «Excavación…», \
«Instalación…», «Etiquetado…», «Entrega…», «Limpieza…».
- Describe solo lo observable. No afirmes presencia, tipo ni concentración de contaminantes; usa términos \
como «suelo con coloración oscura» o «mancha superficial».
- No incluyas claves de punto, profundidades, fechas ni coordenadas, salvo que sean legibles en la imagen \
o se den en el contexto.
- Sin juicios de valor ni adjetivos subjetivos.

En «observacion» anota, brevemente, cualquier duda de clasificación o detalle que requiera verificación humana \
(o cadena vacía)."""

ESQUEMA = {
    "type": "object",
    "properties": {
        "categoria": {"type": "string", "enum": list(CATEGORIAS)},
        "pie": {"type": "string"},
        "confianza": {"type": "string", "enum": ["alta", "media", "baja"]},
        "observacion": {"type": "string"},
    },
    "required": ["categoria", "pie", "confianza", "observacion"],
    "additionalProperties": False,
}


@dataclass
class Clasificacion:
    categoria: str
    pie: str
    confianza: str
    observacion: str


class ErrorClasificacion(Exception):
    pass


def contar_palabras(texto: str) -> int:
    return len(texto.split())


def normalizar_pie(pie: str) -> str:
    pie = " ".join(pie.split()).strip().rstrip(".")
    return pie[:1].upper() + pie[1:] if pie else pie


def _pedir(cliente: Any, contenido: list[dict[str, Any]]) -> Clasificacion:
    r = cliente.beta.messages.create(
        model=MODELO,
        max_tokens=2000,
        system=SISTEMA,
        messages=[{"role": "user", "content": contenido}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": ESQUEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if r.stop_reason == "refusal":
        raise ErrorClasificacion("El modelo declinó clasificar la imagen")
    if r.stop_reason == "max_tokens":
        raise ErrorClasificacion("Respuesta incompleta del modelo")
    texto = next((b.text for b in r.content if b.type == "text"), "")
    try:
        d = json.loads(texto)
    except json.JSONDecodeError as e:
        raise ErrorClasificacion(f"Respuesta no válida: {e}") from e
    return Clasificacion(d["categoria"], normalizar_pie(d["pie"]), d["confianza"], d.get("observacion", ""))


def clasificar(contenido_imagen: bytes, contexto: str = "", cliente: Any | None = None) -> Clasificacion:
    """Clasifica una fotografía y genera su pie. Reintenta una vez si el pie excede el máximo de palabras."""
    cliente = cliente or anthropic.Anthropic()
    imagen = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                          "data": base64.standard_b64encode(preparar_imagen(contenido_imagen)).decode()}}
    texto = "Clasifica la fotografía y redacta su pie."
    if contexto:
        texto += f"\n\nContexto del proyecto (úsalo solo si corresponde a lo que se ve):\n{contexto}"
    c = _pedir(cliente, [imagen, {"type": "text", "text": texto}])
    if contar_palabras(c.pie) > MAX_PALABRAS:
        c = _pedir(cliente, [imagen, {"type": "text", "text": texto + (
            f"\n\nTu propuesta anterior tenía {contar_palabras(c.pie)} palabras: «{c.pie}». "
            f"Redúcela a {MAX_PALABRAS} palabras o menos conservando la información esencial.")}])
    return c
