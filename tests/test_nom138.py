from caepsa.normativa.nom138 import PARAMETROS, UsoSuelo, identificar_parametro, lmp_aplicable, parametros_requeridos

A, R, I = UsoSuelo.AGRICOLA, UsoSuelo.RESIDENCIAL, UsoSuelo.INDUSTRIAL


def test_lmp_tabla2_fracciones():
    assert [lmp_aplicable("HFL", [u]) for u in (A, R, I)] == [200, 200, 500]
    assert [lmp_aplicable("HFM", [u]) for u in (A, R, I)] == [1200, 1200, 5000]
    assert [lmp_aplicable("HFP", [u]) for u in (A, R, I)] == [3000, 1500, 6000]


def test_lmp_tabla3_btex():
    assert lmp_aplicable("BENCENO", [A]) == 6
    assert lmp_aplicable("TOLUENO", [I]) == 100
    assert lmp_aplicable("ETILBENCENO", [A]) == 10
    assert lmp_aplicable("XILENOS", [R]) == 40


def test_uso_mixto_aplica_el_mas_estricto():
    assert lmp_aplicable("HFP", [A, R]) == 1500
    assert lmp_aplicable("HFL", [A, I]) == 200


def test_tabla1_parametros_por_producto():
    assert set(parametros_requeridos("Gasolinas")) == {"HFL", "BENCENO", "TOLUENO", "ETILBENCENO", "XILENOS"}
    assert set(parametros_requeridos("Diésel")) == {"HFM", *[k for k, p in PARAMETROS.items() if p.grupo.name == "HAP"]}
    assert len(parametros_requeridos("Petróleo crudo")) == len(PARAMETROS)
    assert parametros_requeridos(None) == ()


def test_identificar_parametro():
    assert identificar_parametro("Etilbenceno") == "ETILBENCENO"
    assert identificar_parametro("Benceno") == "BENCENO"
    assert identificar_parametro("Hidrocarburos Fracción Ligera (C5-C10)") == "HFL"
    assert identificar_parametro("m,p-Xileno") == "XILENOS"
    assert identificar_parametro("Humedad") is None
