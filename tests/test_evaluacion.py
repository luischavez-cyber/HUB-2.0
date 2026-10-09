from caepsa.normativa.evaluacion import CUMPLE, EXCEDE, INDETERMINADO, NO_DETECTADO, evaluar, resumen
from caepsa.normativa.nom138 import UsoSuelo

A = [UsoSuelo.AGRICOLA]


def fila(muestra, parametro, valor, menor=False, ld=None, punto="P1", zona="Zona 1"):
    return {"muestra": muestra, "punto": punto, "zona": zona, "parametro": parametro, "valor": valor,
            "menor_que": menor, "limite_deteccion": ld, "unidad": "mg/kg"}


def test_estados_por_resultado():
    m = evaluar([
        fila("M1", "HFL", 200),            # igual al LMP: cumple
        fila("M1", "BENCENO", 6.01),       # excede
        fila("M1", "TOLUENO", 0.5, True),  # no detectado
        fila("M1", "XILENOS", 50, True),   # LD > LMP
    ], A, None)[0]
    estados = {r.parametro: r.estado for r in m.resultados}
    assert estados == {"HFL": CUMPLE, "BENCENO": EXCEDE, "TOLUENO": NO_DETECTADO, "XILENOS": INDETERMINADO}
    assert m.estado == EXCEDE and m.excedencias == ["BENCENO"]


def test_faltantes_tabla1_hacen_indeterminado():
    m = evaluar([fila("M1", "HFL", 10)], A, "Gasolinas")[0]
    assert m.estado == INDETERMINADO
    assert set(m.faltantes) == {"BENCENO", "TOLUENO", "ETILBENCENO", "XILENOS"}


def test_resumen():
    ms = evaluar([fila("M1", "HFL", 450, punto="P1"), fila("M2", "HFL", 20, punto="P2", zona="Periferia")], A, None)
    s = resumen(ms)
    assert s["por_estado"] == {EXCEDE: 1, CUMPLE: 1}
    assert s["puntos_con_excedencia"] == ["P1"]
    assert s["maximos"]["HFL"] == 450


def test_uso_mixto_referencia():
    m = evaluar([fila("M1", "HFP", 2000)], [UsoSuelo.AGRICOLA, UsoSuelo.RESIDENCIAL], None)[0]
    assert m.estado == EXCEDE and m.resultados[0].lmp == 1500
    assert "6.1.3" in m.resultados[0].referencia
