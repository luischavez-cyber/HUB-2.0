"""Sitio SINTÉTICO para pruebas del Módulo 6 (no son datos reales de Nueva Italia)."""
from caepsa.dispersion import medio_fisico as mf
from caepsa.laboratorio.captura import importar_csv
from caepsa.proyectos import Proyecto

X0, Y0 = 801200.0, 2108700.0
# punto, zona, dx, dy, [(profundidad, HFL)]
PUNTOS = [
    ("Z1-P01", "Zona 1", 0, 0, [(0.3, 2500), (1.0, 900), (2.0, 350)]),   # vertical abierta
    ("Z1-P02", "Zona 1", 8, -10, [(0.3, 1200), (1.0, 150)]),
    ("Z2-P03", "Zona 2", 15, -25, [(0.3, 640), (1.0, 90)]),
    ("Z2-P04", "Zona 2", -12, -18, [(0.3, 310), (1.0, 40)]),
    ("Z3-P05", "Zona 3", 25, -45, [(0.3, 180), (1.0, 20)]),
    ("PER-P06", "Periferia", 30, -70, [(0.3, 260), (1.0, 30)]),        # periferia que excede
    ("PER-P07", "Periferia", -40, 10, [(0.3, 15)]),
    ("PER-P08", "Periferia", 45, 20, [(0.3, "<10")]),
]


def crear(nombre="Dispersión sintética", con_medio=True) -> Proyecto:
    p = Proyecto.crear(nombre)
    p.actualizar_ficha({"usos_suelo": ["agricola"], "producto": "Gasolinas", "utm_zona": "13Q"})
    filas = ["muestra,punto,zona,profundidad_m,utm_x,utm_y,fecha_muestreo,parametro,valor"]
    for clave, zona, dx, dy, prof in PUNTOS:
        for d, hfl in prof:
            m = f"{clave}-{d:.1f}"
            base = f"{m},{clave},{zona},{d:.2f},{X0 + dx},{Y0 + dy},12/03/2025"
            filas.append(f"{base},HFL,{hfl}")
            filas += [f"{base},{b},<0.002" for b in ("BENCENO", "TOLUENO", "ETILBENCENO", "XILENOS")]
    assert importar_csv(p, "\n".join(filas) + "\n") == []
    if con_medio:
        f = "Levantamiento de campo CAEPSA, 12/03/2025"
        mf.guardar(p, {
            "origen_x": {"valor": X0, "fuente": f}, "origen_y": {"valor": Y0, "fuente": f},
            "volumen_derramado_l": {"valor": 3000, "fuente": "Reporte de emergencia del transportista"},
            "pendiente_pct": {"valor": 3.5, "fuente": f},
            "direccion_pendiente": {"valor": "S", "fuente": f},
            "textura": {"valor": "franco arenoso", "fuente": "Análisis granulométrico, laboratorio"},
            "conductividad_hidraulica_cm_s": {"valor": 2e-3, "fuente": "Prueba de infiltración en campo"},
            "porosidad_efectiva": {"valor": 0.25, "fuente": "Prueba de laboratorio"},
            "unidad_geologica": {"valor": "Aluvión cuaternario", "fuente": "Carta geológica SGM"},
            "tipo_cuerpo_agua": {"valor": "canal de riego", "fuente": f},
            "cuerpo_agua": {"valor": "Canal lateral", "fuente": f},
            "distancia_cuerpo_agua_m": {"valor": 180, "fuente": f},
            "direccion_cuerpo_agua": {"valor": "S", "fuente": f},
            "profundidad_nivel_freatico_m": {"valor": 8, "fuente": "Censo de pozos CONAGUA"},
            "cobertura_vegetal": {"valor": "Huerta de limón", "fuente": f},
            "precipitacion_anual_mm": {"valor": 820, "fuente": "Estación climatológica SMN"},
            "meses_lluvia": {"valor": "junio a octubre", "fuente": "Estación climatológica SMN"},
            "elevacion_msnm": {"valor": 390},  # sin fuente: no debe usarse
        })
    return p
