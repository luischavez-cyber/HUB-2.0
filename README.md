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
alertas, clasifica fotografías, revisa el borrador del informe, genera el Capítulo 5 de dispersión, genera el informe completo y exporta tablas Excel/Word y la sección fotográfica. El modelo **no calcula LMP de memoria**: los obtiene de las herramientas
(`caepsa/asistente/herramientas.py`), que llaman al mismo motor determinista que usan las pantallas. Cada
acción del agente se muestra en el chat y queda en la bitácora del proyecto.

## Módulos

| # | Módulo | Estado |
|---|--------|--------|
| 1 | Gestión de Proyectos: espacio por proyecto (BD SQLite + carpeta de archivos), ficha, tablero de avance y alertas, versiones (instantáneas), bitácora antes/después | ✅ Etapa 1 |
| 2 | Extracción de resultados de laboratorio (pdfplumber) + captura/corrección manual + importación CSV | ✅ Etapa 1 |
| 3 | Evaluación NOM-138: LMP por uso de suelo (Tablas 2 y 3), parámetros por producto (Tabla 1), uso mixto = más estricto, tabla filtrable por zona/estado, exportación Excel y Word | ✅ Etapa 1 |
| 4 | Gestión fotográfica: clasificación por etapa y pies técnicos ≤ 15 palabras con Claude Vision, EXIF (fecha, GPS→UTM) y asociación automática al punto de muestreo más cercano (≤ 30 m), reclasificación manual que la IA no sobrescribe, sección fotográfica en Word | ✅ Etapa 2 |
| 5 | Revisión técnica ambiental: verificaciones automáticas contra la base del proyecto y la NOM-138 + revisión completa con IA desde la perspectiva SEMARNAT/ASEA, hallazgos con criticidad, riesgo y recomendación, Índice de Calidad Técnica 0–100, historial por versión del borrador, dictamen Word y matriz Excel | ✅ Etapa 3 |
| 6 | Análisis de dispersión: datos del medio físico con fuente obligatoria, distribución espacial y vertical de la afectación, delimitación, área y volumen preliminar, matriz de susceptibilidad, receptores, Figura 5.1 y Capítulo 5 en Word (plantilla o redacción con IA con verificación de cifras) | ✅ Etapa 4 |
| 7 | Generación del Informe de Caracterización en Word: portada, índice, capítulos 1–10 y anexos con los datos de todos los módulos, plantilla institucional opcional, marcadores [COMPLETAR] para lo no sustentado y revisión técnica automática del informe generado | ✅ Etapa 5 |

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

## Revisión técnica (Módulo 5)

El borrador (.docx o .pdf) se revisa en dos capas:

1. **Verificaciones automáticas** (deterministas, con la celda o cita que las origina): cita de la NOM-138 vigente
   (y uso de la versión 2003 sustituida), LMP citados contra el catálogo para el uso de suelo del proyecto, valores
   de las tablas contra los resultados del laboratorio, dictamen «Cumple» en muestras que exceden, afirmaciones de
   cumplimiento contrarias a los resultados, muestras que exceden y no se mencionan, uso de suelo distinto al del
   proyecto, conteos de muestras y puntos, coordenadas fuera de rango o distintas a las registradas, fechas
   inválidas y fechas de muestreo omitidas, unidades, secciones esperadas, cadena de custodia y acreditación.
2. **Revisión con IA** (Claude) como dictaminador de la autoridad: información insuficiente, ambigua o
   contradictoria, vacíos respecto a la NOM-138 y recomendaciones. Cada hallazgo trae cita textual; si la cita no
   se encuentra en el documento, se marca y pesa la mitad en el índice. Documentos muy grandes no se truncan: se
   pide dividirlos.

**Índice de Calidad Técnica** = Σ peso × subíndice, con subíndice = 100 − penalizaciones (crítica 20, alta 10,
media 5, baja 2, informativa 0) por dimensión: consistencia de datos 35 %, sustento normativo 30 %, completitud
20 %, claridad 15 %. ≥ 85 apto para ingreso; 70–84 ajustes menores; 50–69 correcciones importantes; < 50 no apto.
Un hallazgo solo se descarta con justificación (queda en bitácora); el «ICT vigente» excluye los descartados.
Con hallazgos críticos abiertos el dictamen nunca es «apto», aunque el puntaje sea alto. Los marcadores
`[COMPLETAR…]`/`[DATO PENDIENTE…]` generan un hallazgo crítico (más uno por sección afectada).

## Análisis de dispersión (Módulo 6)

- **Medio físico con fuente obligatoria.** Topografía, suelo, geología, hidrología superficial y subterránea,
  vegetación, clima y datos del evento. Un dato sin fuente se guarda, pero no se usa; lo que falta aparece en el
  capítulo como `[DATO PENDIENTE: …]`.
- **Cálculos deterministas** a partir de resultados y coordenadas: parámetro indicador (mayor relación valor/LMP),
  extensión desde el origen, dirección de la dispersión y coincidencia con la pendiente, área de la envolvente de
  puntos con excedencia, volumen preliminar (central y conservador), delimitación horizontal (excedencias en la
  periferia) y vertical (excedencia en la muestra más profunda) y tiempo de tránsito vertical (solo con K y
  porosidad documentadas).
- **Matriz de susceptibilidad**: tamizaje cualitativo con umbrales explícitos y editables (constantes al inicio de
  `caepsa/dispersion/analisis.py`); no es un criterio normativo ni sustituye una modelación numérica.
- **Capítulo 5** (secciones 5.1–5.8, Tablas 5.1–5.3 y Figura 5.1). Sin IA se redacta por plantilla; con IA, toda
  cifra del texto que no exista en los datos se resalta en amarillo en el Word para su verificación.

## Informe de Caracterización (Módulo 7)

Estructura: portada, índice, 1 Antecedentes, 2 Marco legal (solo NOM-138; otras disposiciones quedan para el
responsable técnico), 3 Metodología de muestreo, 4 Resultados y evaluación normativa (tabla NOM-138 en página
horizontal), 5 Análisis de dispersión (Módulo 6), 6 Identificación de la pluma, 7 Evaluación de daños,
8 Conclusiones, 9 Plan de saneamiento (metas de limpieza = LMP aplicables; técnica, muestreo de comprobación y
programa quedan por completar), 10 Memoria fotográfica (Módulo 4) y anexos.

- Todo dato proviene de la base del proyecto; lo que no se puede sustentar se inserta como `[COMPLETAR: …]`
  resaltado en amarillo y se cuenta.
- **Plantilla institucional** (.docx): se conservan estilos, encabezado, pie y logotipo; se crean los estilos que
  falten.
- El índice y la paginación son campos de Word: se actualizan al abrir el archivo.
- El informe se guarda como borrador del proyecto y puede pasar automáticamente por la revisión técnica del
  Módulo 5. Las pruebas exigen que el informe generado no tenga **ninguna** inconsistencia de datos, normativa o
  estructura según ese revisor.

## Pendientes de datos reales

- El extractor se probó con PDFs sintéticos en dos formatos comunes (por muestra y matricial). Debe calibrarse con
  el **PDF real de NOVALABSA** (42 muestras, 17 puntos), que no estaba disponible en el repositorio.
- Las secciones esperadas del informe (Módulo 5) siguen la estructura definida por CAEPSA; deben ajustarse al
  **Informe de Nueva Italia** cuando esté disponible (`SECCIONES_ESPERADAS` en `caepsa/revision/verificaciones.py`).
- Los umbrales de la matriz de susceptibilidad son una propuesta para validación del equipo técnico de CAEPSA.
- Plantilla de captura: `data/plantilla_resultados.csv`.
