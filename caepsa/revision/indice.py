"""Hallazgos de revisión e Índice de Calidad Técnica (ICT) del informe.

El ICT es un indicador interno de CAEPSA (0–100), calculado de forma determinista a partir de los
hallazgos para que dos revisiones del mismo borrador sean comparables. No sustituye la resolución de la
autoridad.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

CRITICIDADES = {"critica": 20.0, "alta": 10.0, "media": 5.0, "baja": 2.0, "info": 0.0}
ETIQUETA_CRITICIDAD = {"critica": "Crítica", "alta": "Alta", "media": "Media", "baja": "Baja", "info": "Informativa"}

DIMENSIONES: dict[str, tuple[str, float]] = {
    "consistencia": ("Consistencia de datos", 0.35),
    "normativo": ("Sustento normativo (NOM-138)", 0.30),
    "completitud": ("Completitud", 0.20),
    "claridad": ("Claridad y precisión", 0.15),
}

CATEGORIAS: dict[str, tuple[str, str]] = {
    "inconsistencia_laboratorio": ("Inconsistencia con resultados de laboratorio", "consistencia"),
    "inconsistencia_tabla_texto": ("Inconsistencia entre tablas y texto", "consistencia"),
    "contradictorio": ("Información contradictoria", "consistencia"),
    "coordenadas": ("Error de coordenadas", "consistencia"),
    "fechas": ("Fechas inconsistentes", "consistencia"),
    "fuera_de_rango": ("Dato fuera de rango", "consistencia"),
    "vacio_regulatorio": ("Vacío regulatorio", "normativo"),
    "referencia_normativa": ("Referencia normativa", "normativo"),
    "insuficiente": ("Información insuficiente", "completitud"),
    "estructura": ("Estructura del informe", "completitud"),
    "ambiguo": ("Información ambigua", "claridad"),
    "redaccion": ("Redacción y presentación", "claridad"),
}

# Hallazgos de IA cuya cita no se encontró en el documento pesan la mitad (pueden ser imprecisos).
FACTOR_SIN_EVIDENCIA = 0.5


@dataclass
class Hallazgo:
    origen: str  # "automatica" | "ia"
    categoria: str
    criticidad: str
    ubicacion: str
    descripcion: str
    evidencia: str = ""
    riesgo: str = ""
    recomendacion: str = ""
    referencia: str = ""
    evidencia_localizada: bool | None = None
    estado: str = "abierto"  # "abierto" | "atendido" | "descartado"
    nota: str = ""
    id: int | None = None

    def __post_init__(self) -> None:
        if self.categoria not in CATEGORIAS:
            raise ValueError(f"Categoría desconocida: {self.categoria}")
        if self.criticidad not in CRITICIDADES:
            raise ValueError(f"Criticidad desconocida: {self.criticidad}")

    @property
    def dimension(self) -> str:
        return CATEGORIAS[self.categoria][1]

    @property
    def penalizacion(self) -> float:
        base = CRITICIDADES[self.criticidad]
        if self.origen == "ia" and self.evidencia_localizada is False:
            base *= FACTOR_SIN_EVIDENCIA
        return base

    def a_dict(self) -> dict[str, Any]:
        return asdict(self)


def calcular_ict(hallazgos: Iterable[Hallazgo]) -> dict[str, Any]:
    """ICT y subíndices. Los hallazgos descartados no penalizan; los atendidos sí (hasta una nueva revisión)."""
    penal = {d: 0.0 for d in DIMENSIONES}
    for h in hallazgos:
        if h.estado != "descartado":
            penal[h.dimension] += h.penalizacion
    sub = {d: max(0.0, 100.0 - p) for d, p in penal.items()}
    ict = sum(sub[d] * DIMENSIONES[d][1] for d in DIMENSIONES)
    return {"ict": round(ict, 1), "subindices": {d: round(v, 1) for d, v in sub.items()},
            "interpretacion": interpretar(ict)}


def interpretar(ict: float) -> str:
    if ict >= 85:
        return "Apto para ingreso a la autoridad"
    if ict >= 70:
        return "Requiere ajustes menores"
    if ict >= 50:
        return "Requiere correcciones importantes"
    return "No apto: alto riesgo de observaciones o prevención"
