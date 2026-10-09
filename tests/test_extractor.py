"""Pruebas del extractor con PDFs SINTÉTICOS generados aquí (no son datos reales de laboratorio)."""
from io import BytesIO

from reportlab.lib.pagesizes import letter
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet

from caepsa.laboratorio.captura import guardar_extraccion
from caepsa.laboratorio.extractor import extraer, interpretar_valor
from caepsa.proyectos import Proyecto

ESTILO = TableStyle([("GRID", (0, 0), (-1, -1), 0.5, "black")])


def _pdf(elementos):
    buf = BytesIO()
    SimpleDocTemplate(buf, pagesize=letter).build(elementos)
    return buf.getvalue()


def pdf_por_muestra():
    st = getSampleStyleSheet()["Normal"]
    el = []
    for clave, punto, hfl, benceno in (("Z1-P01-M1", "Z1-P01", "512.3", "<0.002"), ("Z2-P05-M2", "Z2-P05", "85.1", "0.004")):
        for linea in (f"Identificación de la muestra: {clave}", f"Punto de muestreo: {punto}", "Zona 1",
                      "Profundidad: 0.30 m", "Coordenadas UTM 13Q X: 801234.5 Y: 2108765.2",
                      "Fecha de muestreo: 12/03/2025"):
            el.append(Paragraph(linea, st))
        el.append(Table([["Parámetro", "Resultado", "Límite de detección", "Unidad", "Método"],
                         ["Hidrocarburos fracción ligera", hfl, "10", "mg/kg", "NMX-AA-105-SCFI-2014"],
                         ["Benceno", benceno, "0.002", "mg/kg", "EPA 8260B"],
                         ["Tolueno", "N.D.", "0.002", "mg/kg", "EPA 8260B"]], style=ESTILO))
        el.append(PageBreak())
    return _pdf(el)


def pdf_matricial():
    return _pdf([Table([
        ["Parámetro", "Unidad", "Z1-P01-M1", "Z1-P01-M2", "P-PER-M1"],
        ["Profundidad (m)", "", "0.30", "1.00", "0.30"],
        ["Coordenada X", "", "801234.5", "801234.5", "801500.0"],
        ["Coordenada Y", "", "2108765.2", "2108765.2", "2109001.0"],
        ["Fracción ligera", "mg/kg", "1,250.0", "<10", "15.2"],
        ["Etilbenceno", "mg/kg", "<0.002", "0.010", "<0.002"],
    ], style=ESTILO)])


def test_interpretar_valor():
    assert interpretar_valor("1,250.5") == (1250.5, False)
    assert interpretar_valor("< 0.5") == (0.5, True)
    assert interpretar_valor("N.D.") == (None, True)
    assert interpretar_valor("mg/kg") is None


def test_extraccion_por_muestra():
    ext = extraer(pdf_por_muestra())
    assert [m.clave for m in ext.muestras] == ["Z1-P01-M1", "Z2-P05-M2"]
    m = ext.muestras[0]
    assert (m.punto, m.profundidad_m, m.utm_x, m.utm_y, m.fecha_muestreo) == \
        ("Z1-P01", "0.30", 801234.5, 2108765.2, "12/03/2025")
    assert m.resultados["HFL"].valor == 512.3 and m.resultados["HFL"].metodo == "NMX-AA-105-SCFI-2014"
    assert m.resultados["BENCENO"].menor_que and m.resultados["BENCENO"].valor == 0.002
    assert m.resultados["TOLUENO"].menor_que and m.resultados["TOLUENO"].limite_deteccion == 0.002
    assert m.faltantes == []


def test_extraccion_matricial_y_guardado():
    ext = extraer(pdf_matricial())
    assert {m.clave for m in ext.muestras} == {"Z1-P01-M1", "Z1-P01-M2", "P-PER-M1"}
    m = next(x for x in ext.muestras if x.clave == "Z1-P01-M1")
    assert m.resultados["HFL"].valor == 1250.0 and m.profundidad_m == "0.30" and m.utm_x == 801234.5
    assert "punto" in m.faltantes  # se captura manualmente
    p = Proyecto.crear("X")
    assert guardar_extraccion(p, ext) == 6
    assert {f["origen"] for f in p.tabla_resultados()} == {"pdf"}
