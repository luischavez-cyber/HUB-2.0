import pytest

from caepsa.laboratorio.captura import importar_csv
from caepsa.proyectos import Proyecto, campos_faltantes
from caepsa.tablero import estado


def test_crear_y_listar_con_espacio_propio():
    p = Proyecto.crear("Nueva Italia Km 176+500", usuario="qa", cliente="Cliente X")
    assert (p.ruta / "proyecto.db").exists() and (p.ruta / "archivos").is_dir()
    assert Proyecto.listar()[0]["clave"] == p.clave
    assert Proyecto.crear("Nueva Italia Km 176+500").clave != p.clave
    assert p.ficha()["cliente"] == "Cliente X"
    assert any(c.clave == "expediente" for c in campos_faltantes(p.ficha()))


def test_producto_fuera_de_tabla1_se_rechaza():
    p = Proyecto.crear("X")
    with pytest.raises(ValueError):
        p.actualizar_ficha({"producto": "Biodiesel"})


def test_bitacora_registra_antes_y_despues():
    p = Proyecto.crear("X", usuario="ana")
    p.guardar_muestra("M1", "P1", profundidad_m="0.30")
    p.guardar_resultado("M1", "HFL", 150)
    p.guardar_resultado("M1", "HFL", 250)
    ult = p.bitacora()[0]
    assert ult["entidad"] == "resultado" and ult["usuario"] == "ana"
    assert '"valor": 150' in ult["antes"] and '"valor": 250' in ult["despues"]


def test_instantanea_y_restauracion():
    p = Proyecto.crear("X")
    p.guardar_muestra("M1", "P1")
    p.guardar_resultado("M1", "HFL", 100)
    v = p.crear_instantanea("validado")
    p.guardar_resultado("M1", "HFL", 999)
    p.restaurar_instantanea(v)
    assert [f["valor"] for f in p.tabla_resultados()] == [100]
    assert len(p.versiones()) == 2  # la versión + respaldo automático previo a restaurar


def test_importar_csv_y_tablero():
    p = Proyecto.crear("X")
    p.actualizar_ficha({"usos_suelo": ["agricola"], "muestras_esperadas": "42", "puntos_esperados": "17"})
    errores = importar_csv(p, (
        "muestra,punto,zona,profundidad_m,utm_x,utm_y,parametro,valor\n"
        "M1,P1,Zona 1,0.30,800100,2108000,HFL,350\n"
        "M1,P1,Zona 1,0.30,800100,2108000,Benceno,<0.002\n"
        "M2,P2,Periferia,0.30,,,Humedad,12\n"
    ))
    assert errores == ["Fila 4: parámetro no reconocido en la NOM-138: 'Humedad'"]
    filas = p.tabla_resultados()
    benceno = next(f for f in filas if f["parametro"] == "BENCENO")
    assert benceno["menor_que"] == 1 and benceno["valor"] == 0.002
    _, alertas = estado(p)
    textos = " ".join(a.mensaje for a in alertas)
    assert "≠ esperadas (42)" in textos and "≠ esperados (17)" in textos
    assert "sin coordenadas UTM" in textos and "exceden LMP (Fracción ligera)" in textos
