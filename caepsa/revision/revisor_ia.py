"""Revisión del borrador con Claude desde la perspectiva de la autoridad ambiental (SEMARNAT / ASEA)."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

import anthropic

from ..normativa.nom138 import NORMA, PUBLICACION_DOF
from .documento import Documento, normalizar
from .indice import CATEGORIAS, CRITICIDADES, Hallazgo

MODELO = os.environ.get("CAEPSA_MODELO", "claude-opus-5-5")
# Por encima de este tamaño no se envía el documento (no se trunca en silencio): se pide dividirlo.
MAX_CARACTERES = 600_000

SISTEMA = f"""Actúas como dictaminador técnico de la autoridad ambiental mexicana (SEMARNAT o ASEA) que revisa \
un Informe de Caracterización de un sitio contaminado por derrame de hidrocarburos, elaborado por Consultoría \
Ambiental Estudios y Proyectos S.A. de C.V. (CAEPSA). Tu objetivo es anticipar las observaciones, prevenciones o \
requerimientos de información que emitiría la autoridad, para que CAEPSA las corrija antes del ingreso.

Marco normativo: exclusivamente la {NORMA} (DOF {PUBLICACION_DOF}). No uses otras normas, guías extranjeras ni \
criterios externos como fundamento. En «referencia_nom138» cita la tabla o apartado solo si estás seguro; si no, \
escribe «NOM-138 (verificar apartado)»; si el hallazgo no es normativo, deja cadena vacía.

Busca, entre otros:
- Información insuficiente para sustentar conclusiones (metodología, criterios de selección de puntos, \
profundidades, extensión del área afectada, volumen estimado de suelo afectado, acreditación del laboratorio).
- Información ambigua (términos vagos, unidades no declaradas, afirmaciones sin dato).
- Contradicciones entre secciones, entre tablas y texto, o entre conclusiones y resultados.
- Vacíos regulatorios respecto a la {NORMA}: parámetros que debían analizarse según el producto, \
comparación contra LMP del uso de suelo correcto, uso mixto, delimitación de la afectación.
- Errores de coordenadas, fechas inconsistentes y datos fuera de rango.

Reglas estrictas:
- «evidencia» debe ser una cita textual exacta y breve (máx. 300 caracteres) del documento. Si el hallazgo es \
una ausencia de información, deja «evidencia» vacía y explica en «descripcion» qué falta y dónde debería estar.
- No inventes datos del proyecto ni resultados. Usa el resumen de datos del proyecto solo como referencia.
- No repitas los hallazgos de la verificación automática que se te proporcionan; complementa.
- Criticidad: «critica» = motivo probable de prevención o rechazo; «alta» = observación formal segura; \
«media» = aclaración probable; «baja» = mejora de calidad; «info» = comentario sin impacto.
- Español técnico y conciso. «recomendacion» debe ser una acción concreta y verificable."""

ESQUEMA = {
    "type": "object",
    "properties": {
        "resumen": {"type": "string"},
        "fortalezas": {"type": "array", "items": {"type": "string"}},
        "hallazgos": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "categoria": {"type": "string", "enum": list(CATEGORIAS)},
                "criticidad": {"type": "string", "enum": list(CRITICIDADES)},
                "ubicacion": {"type": "string"},
                "evidencia": {"type": "string"},
                "descripcion": {"type": "string"},
                "riesgo_regulatorio": {"type": "string"},
                "recomendacion": {"type": "string"},
                "referencia_nom138": {"type": "string"},
            },
            "required": ["categoria", "criticidad", "ubicacion", "evidencia", "descripcion",
                         "riesgo_regulatorio", "recomendacion", "referencia_nom138"],
            "additionalProperties": False,
        }},
    },
    "required": ["resumen", "fortalezas", "hallazgos"],
    "additionalProperties": False,
}


class ErrorRevision(Exception):
    pass


@dataclass
class ResultadoIA:
    resumen: str
    fortalezas: list[str]
    hallazgos: list[Hallazgo] = field(default_factory=list)


def evidencia_localizada(evidencia: str, texto_normalizado: str) -> bool | None:
    """True si la cita aparece en el documento (admite «…» entre fragmentos); None si no hay cita."""
    if not evidencia.strip():
        return None
    fragmentos = [f for f in (normalizar(x) for x in re.split(r"\.\.\.|…|\[\.\.\.\]", evidencia)) if len(f) >= 8]
    if not fragmentos:
        return normalizar(evidencia) in texto_normalizado
    return all(f in texto_normalizado for f in fragmentos)


def revisar(doc: Documento, contexto_proyecto: str, automaticos: list[Hallazgo],
            cliente: Any | None = None) -> ResultadoIA:
    texto = doc.como_texto_marcado()
    if len(texto) > MAX_CARACTERES:
        raise ErrorRevision(
            f"El documento tiene {len(texto):,} caracteres y excede el máximo de {MAX_CARACTERES:,} para una sola "
            "revisión. Divida el borrador (por ejemplo, cuerpo y anexos) y revise cada parte.")
    cliente = cliente or anthropic.Anthropic()
    previos = "\n".join(f"- [{h.criticidad}] {h.descripcion}" for h in automaticos) or "(ninguno)"
    mensaje = (
        f"<datos_del_proyecto>\n{contexto_proyecto}\n</datos_del_proyecto>\n\n"
        f"<hallazgos_verificacion_automatica>\n{previos}\n</hallazgos_verificacion_automatica>\n\n"
        f"<borrador nombre=\"{doc.nombre}\">\n{texto}\n</borrador>\n\n"
        "Revisa el borrador completo y devuelve tu dictamen.")
    with cliente.beta.messages.stream(
        model=MODELO,
        max_tokens=32000,
        system=SISTEMA,
        messages=[{"role": "user", "content": mensaje}],
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": ESQUEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    ) as stream:
        r = stream.get_final_message()
    if r.stop_reason == "refusal":
        raise ErrorRevision("El modelo declinó revisar el documento")
    if r.stop_reason == "max_tokens":
        raise ErrorRevision("La revisión excedió la longitud máxima de respuesta; divida el documento")
    salida = next((b.text for b in r.content if b.type == "text"), "")
    try:
        datos = json.loads(salida)
    except json.JSONDecodeError as e:
        raise ErrorRevision(f"Respuesta del modelo no válida: {e}") from e

    todo = normalizar("\n".join(b.texto for b in doc.bloques))
    hallazgos = [
        Hallazgo("ia", d["categoria"], d["criticidad"], d["ubicacion"], d["descripcion"],
                 evidencia=d["evidencia"], riesgo=d["riesgo_regulatorio"], recomendacion=d["recomendacion"],
                 referencia=d["referencia_nom138"], evidencia_localizada=evidencia_localizada(d["evidencia"], todo))
        for d in datos["hallazgos"]
    ]
    return ResultadoIA(datos["resumen"], datos["fortalezas"], hallazgos)
