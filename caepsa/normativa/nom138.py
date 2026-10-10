"""Catálogo normativo NOM-138-SEMARNAT/SSA1-2012.

Única fuente de verdad regulatoria de la plataforma. Todo valor aquí está
transcrito de la norma publicada en el DOF el 10/09/2013; no se incorpora
ningún criterio externo (EPA, normas extranjeras, guías internacionales).

Cada límite y regla lleva su referencia a la tabla o apartado de la norma.
Las referencias marcadas con ``VERIFICAR_DOF`` deben cotejarse contra el
texto oficial por el responsable técnico antes de emitir un informe.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

NORMA = "NOM-138-SEMARNAT/SSA1-2012"
TITULO = ("Límites máximos permisibles de hidrocarburos en suelos y lineamientos para el muestreo en la "
          "caracterización y especificaciones para la remediación")
PUBLICACION_DOF = "10/09/2013"
UNIDAD = "mg/kg base seca"

# Referencias que el usuario/CAEPSA indicó y deben cotejarse con el DOF.
VERIFICAR_DOF = "cotejar numeración contra texto DOF"


class UsoSuelo(str, Enum):
    """Columnas de uso de suelo de las Tablas 2 y 3 de la norma."""

    AGRICOLA = "agricola"
    RESIDENCIAL = "residencial"
    INDUSTRIAL = "industrial"

    @property
    def etiqueta(self) -> str:
        return {
            UsoSuelo.AGRICOLA: "Agrícola, forestal, pecuario y de conservación",
            UsoSuelo.RESIDENCIAL: "Residencial y recreativo",
            UsoSuelo.INDUSTRIAL: "Industrial y comercial",
        }[self]


class Grupo(str, Enum):
    FRACCION = "Fracciones de hidrocarburos"
    BTEX = "Hidrocarburos monoaromáticos (BTEX)"
    HAP = "Hidrocarburos aromáticos polinucleares (HAP)"


@dataclass(frozen=True)
class Parametro:
    clave: str
    nombre: str
    grupo: Grupo
    tabla: str
    lmp: dict[UsoSuelo, float]
    sinonimos: tuple[str, ...] = ()


def _lmp(agricola: float, residencial: float, industrial: float) -> dict[UsoSuelo, float]:
    return {
        UsoSuelo.AGRICOLA: agricola,
        UsoSuelo.RESIDENCIAL: residencial,
        UsoSuelo.INDUSTRIAL: industrial,
    }


_T2 = "Tabla 2"
_T3 = "Tabla 3"

PARAMETROS: dict[str, Parametro] = {
    p.clave: p
    for p in [
        # Tabla 2 — Límites máximos permisibles para fracciones de hidrocarburos en suelo.
        Parametro("HFL", "Fracción ligera", Grupo.FRACCION, _T2, _lmp(200, 200, 500),
                  ("HFL", "FRACCION LIGERA", "HIDROCARBUROS FRACCION LIGERA", "C5-C10", "C5 A C10")),
        Parametro("HFM", "Fracción media", Grupo.FRACCION, _T2, _lmp(1200, 1200, 5000),
                  ("HFM", "FRACCION MEDIA", "HIDROCARBUROS FRACCION MEDIA", "C10-C28", "C10 A C28")),
        Parametro("HFP", "Fracción pesada", Grupo.FRACCION, _T2, _lmp(3000, 1500, 6000),
                  ("HFP", "FRACCION PESADA", "HIDROCARBUROS FRACCION PESADA", "C28-C40", "C28 A C40")),
        # Tabla 3 — Límites máximos permisibles para hidrocarburos específicos en suelo.
        Parametro("BENCENO", "Benceno", Grupo.BTEX, _T3, _lmp(6, 6, 15), ("BENCENO",)),
        Parametro("TOLUENO", "Tolueno", Grupo.BTEX, _T3, _lmp(40, 40, 100), ("TOLUENO",)),
        Parametro("ETILBENCENO", "Etilbenceno", Grupo.BTEX, _T3, _lmp(10, 10, 25), ("ETILBENCENO",)),
        Parametro("XILENOS", "Xilenos (suma de isómeros)", Grupo.BTEX, _T3, _lmp(40, 40, 100),
                  ("XILENOS", "XILENOS TOTALES", "XILENO", "M,P-XILENO", "O-XILENO")),
        Parametro("BAP", "Benzo[a]pireno", Grupo.HAP, _T3, _lmp(2, 2, 10), ("BENZO(A)PIRENO", "BENZO[A]PIRENO")),
        Parametro("DBAHA", "Dibenzo[a,h]antraceno", Grupo.HAP, _T3, _lmp(2, 2, 10),
                  ("DIBENZO(A,H)ANTRACENO", "DIBENZO[A,H]ANTRACENO")),
        Parametro("BAA", "Benzo[a]antraceno", Grupo.HAP, _T3, _lmp(2, 2, 10), ("BENZO(A)ANTRACENO", "BENZO[A]ANTRACENO")),
        Parametro("BBF", "Benzo[b]fluoranteno", Grupo.HAP, _T3, _lmp(2, 2, 10),
                  ("BENZO(B)FLUORANTENO", "BENZO[B]FLUORANTENO")),
        Parametro("BKF", "Benzo[k]fluoranteno", Grupo.HAP, _T3, _lmp(8, 8, 80),
                  ("BENZO(K)FLUORANTENO", "BENZO[K]FLUORANTENO")),
        Parametro("ICDP", "Indeno(1,2,3-cd)pireno", Grupo.HAP, _T3, _lmp(2, 2, 10),
                  ("INDENO(1,2,3-CD)PIRENO", "INDENO[1,2,3-CD]PIRENO")),
    ]
}

BTEX = ("BENCENO", "TOLUENO", "ETILBENCENO", "XILENOS")
HAP = ("BAP", "DBAHA", "BAA", "BBF", "BKF", "ICDP")

# Tabla 1 — Hidrocarburos que deberán analizarse en función del producto contaminante.
_L, _M, _P = ("HFL",), ("HFM",), ("HFP",)
PRODUCTOS: dict[str, tuple[str, ...]] = {
    "Mezcla de productos desconocidos derivados del petróleo": _P + _M + _L + HAP + BTEX,
    "Petróleo crudo": _P + _M + _L + HAP + BTEX,
    "Combustóleo": _P + HAP,
    "Parafinas": _P + HAP,
    "Petrolatos": _P + HAP,
    "Aceites derivados del petróleo": _P + HAP,
    "Gasavión": _L + BTEX,
    "Gasolvente": _L + BTEX,
    "Gasolinas": _L + BTEX,
    "Gas nafta": _L + BTEX,
    "Diésel": _M + HAP,
    "Turbosina": _M + HAP,
    "Queroseno": _M + HAP,
    "Creosota": _M + HAP,
}

REFERENCIAS = {
    "parametros_por_producto": f"{NORMA}, Tabla 1",
    "lmp_fracciones": f"{NORMA}, Tabla 2",
    "lmp_especificos": f"{NORMA}, Tabla 3",
    "uso_mixto": f"{NORMA}, apartado 6.1.3 — criterio más estricto en uso mixto ({VERIFICAR_DOF})",
}


def lmp_aplicable(clave: str, usos: list[UsoSuelo] | tuple[UsoSuelo, ...]) -> float:
    """LMP para un parámetro. En uso mixto aplica el valor más estricto (menor)."""
    if not usos:
        raise ValueError("Debe indicarse al menos un uso de suelo")
    p = PARAMETROS[clave]
    return min(p.lmp[u] for u in usos)


def parametros_requeridos(producto: str | None) -> tuple[str, ...]:
    """Parámetros exigidos por la Tabla 1 para el producto; vacío si no se conoce."""
    return PRODUCTOS.get(producto or "", ())


def _normaliza(texto: str) -> str:
    import unicodedata

    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(t.upper().replace("–", "-").split())


_INDICE_SINONIMOS = {
    _normaliza(s): p.clave for p in PARAMETROS.values() for s in (*p.sinonimos, p.nombre, p.clave)
}


def identificar_parametro(texto: str) -> str | None:
    """Mapea un rótulo de laboratorio a la clave del catálogo (o None)."""
    t = _normaliza(texto)
    if t in _INDICE_SINONIMOS:
        return _INDICE_SINONIMOS[t]
    # Coincidencia por contenido, priorizando los sinónimos más largos.
    for sin in sorted(_INDICE_SINONIMOS, key=len, reverse=True):
        if len(sin) >= 4 and sin in t:
            return _INDICE_SINONIMOS[sin]
    return None
