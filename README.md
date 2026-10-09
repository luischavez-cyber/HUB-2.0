# HUB CAEPSA — Auditoría de informes de caracterización (NOM-138-SEMARNAT/SSA1-2012)

Plataforma para **Consultoría Ambiental Estudios y Proyectos S.A. de C.V. (CAEPSA)** para integrar, auditar y
generar informes de caracterización de suelos afectados por derrames de hidrocarburos. Toma como plantilla
estructural el *Informe de Caracterización de Nueva Italia, Michoacán (Km 176+500, Autopista Siglo XXI)*.

**Marco regulatorio fijo:** únicamente la NOM-138-SEMARNAT/SSA1-2012 (DOF 10/09/2013). El catálogo normativo
está en `caepsa/normativa/nom138.py` y cada LMP y regla lleva su tabla o apartado de origen.

## Uso

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...        # solo para el Asistente IA
streamlit run app.py
```

Los datos se guardan en `./workspace` (cámbielo con `CAEPSA_WORKSPACE`). Pruebas: `python -m pytest`.

## Asistente IA (página principal)

Agente conversacional (Claude, con uso de herramientas) que opera toda la plataforma: crea y actualiza proyectos,
recibe el PDF del laboratorio en el chat, extrae y guarda resultados, evalúa contra la NOM-138, informa
alertas, clasifica fotografías y exporta tablas Excel/Word y la sección fotográfica. El modelo **no calcula LMP de memoria**: los obtiene de las herramientas
(`caepsa/asistente/herramientas.py`), que llaman al mismo motor determinista que usan las pantallas. Cada
acción del agente se muestra en el chat y queda en la bitácora del proyecto.

## Módulos

| # | Módulo | Estado |
|---|--------|--------|
| 1 | Gestión de Proyectos: espacio por proyecto (BD SQLite + carpeta de archivos), ficha, tablero de avance y alertas, versiones (instantáneas), bitácora antes/después | ✅ Etapa 1 |
| 2 | Extracción de resultados de laboratorio (pdfplumber) + captura/corrección manual + importación CSV | ✅ Etapa 1 |
| 3 | Evaluación NOM-138: LMP por uso de suelo (Tablas 2 y 3), parámetros por producto (Tabla 1), uso mixto = más estricto, tabla filtrable por zona/estado, exportación Excel y Word | ✅ Etapa 1 |
| 4 | Gestión fotográfica: clasificación por etapa y pies técnicos ≤ 15 palabras con Claude Vision, EXIF (fecha, GPS→UTM) y asociación automática al punto de muestreo más cercano (≤ 30 m), reclasificación manual que la IA no sobrescribe, sección fotográfica en Word | ✅ Etapa 2 |
| 5 | Revisión técnica ambiental (perspectiva SEMARNAT/ASEA, Índice de Calidad Técnica 0–100) | Etapa 3 |
| 6 | Análisis de dispersión de hidrocarburos (Capítulo 5) | Etapa 4 |
| 7 | Generación del informe completo en Word | Etapa 5 |

## Criterios de evaluación (Módulo 3)

- **Cumple**: valor ≤ LMP. **Excede**: valor > LMP (resaltado en rojo).
- **No detectado**: reportado `<LD` con LD ≤ LMP.
- **Indeterminado**: `<LD` con LD > LMP, o la muestra no reporta todos los parámetros que la Tabla 1 exige para el producto.
- Uso de suelo mixto: se aplica el LMP menor. La cita "apartado 6.1.3" está marcada para cotejarse contra el texto del DOF.

## Gestión fotográfica (Módulo 4)

Categorías, en el orden del informe: reconocimiento del sitio, muestreo de suelo, excavaciones y sondeos,
pozos de monitoreo, evidencias de laboratorio y cadena de custodia, cierre de actividades (y "otras evidencias").
Los pies de foto siguen una guía de estilo fija: una oración sin punto final, que inicia con la actividad,
describe solo lo observable y no afirma presencia ni concentración de contaminantes. Si la IA propone más de
15 palabras se le pide que lo reduzca una vez; si persiste queda marcado para revisión. Las propuestas de la IA
quedan como "pendientes de revisión" hasta que una persona las confirma.

## Pendientes de datos reales

- El extractor se probó con PDFs sintéticos en dos formatos comunes (por muestra y matricial). Debe calibrarse con
  el **PDF real de NOVALABSA** (42 muestras, 17 puntos), que no estaba disponible en el repositorio.
- Plantilla de captura: `data/plantilla_resultados.csv`.
