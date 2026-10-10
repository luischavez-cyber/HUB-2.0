"""Almacenamiento: registro central de proyectos + una base SQLite por proyecto."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ESQUEMA_REGISTRO = """
CREATE TABLE IF NOT EXISTS proyectos (
    clave       TEXT PRIMARY KEY,
    nombre      TEXT NOT NULL,
    ruta        TEXT NOT NULL,
    creado      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    actualizado TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""

ESQUEMA_PROYECTO = """
CREATE TABLE IF NOT EXISTS ficha (
    campo TEXT PRIMARY KEY,
    valor TEXT
);
CREATE TABLE IF NOT EXISTS puntos (
    id          INTEGER PRIMARY KEY,
    clave       TEXT NOT NULL UNIQUE,
    zona        TEXT,
    utm_x       REAL,
    utm_y       REAL,
    utm_zona    TEXT,
    descripcion TEXT
);
CREATE TABLE IF NOT EXISTS muestras (
    id             INTEGER PRIMARY KEY,
    clave          TEXT NOT NULL UNIQUE,
    punto_id       INTEGER REFERENCES puntos(id) ON DELETE SET NULL,
    profundidad_m  TEXT,
    fecha_muestreo TEXT,
    folio_lab      TEXT,
    origen         TEXT NOT NULL DEFAULT 'manual',
    pagina_pdf     INTEGER
);
CREATE TABLE IF NOT EXISTS resultados (
    id                INTEGER PRIMARY KEY,
    muestra_id        INTEGER NOT NULL REFERENCES muestras(id) ON DELETE CASCADE,
    parametro         TEXT NOT NULL,
    valor             REAL,
    menor_que         INTEGER NOT NULL DEFAULT 0,
    limite_deteccion  REAL,
    unidad            TEXT,
    metodo            TEXT,
    origen            TEXT NOT NULL DEFAULT 'manual',
    pagina_pdf        INTEGER,
    UNIQUE (muestra_id, parametro)
);
CREATE TABLE IF NOT EXISTS documentos (
    id      INTEGER PRIMARY KEY,
    tipo    TEXT NOT NULL,
    nombre  TEXT NOT NULL,
    ruta    TEXT NOT NULL,
    sha256  TEXT NOT NULL,
    cargado TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS fotografias (
    id                INTEGER PRIMARY KEY,
    documento_id      INTEGER NOT NULL UNIQUE REFERENCES documentos(id) ON DELETE CASCADE,
    categoria         TEXT,
    categoria_origen  TEXT,
    pie               TEXT,
    pie_origen        TEXT,
    confianza         TEXT,
    observacion       TEXT,
    punto             TEXT,
    punto_origen      TEXT,
    fecha_toma        TEXT,
    lat               REAL,
    lon               REAL,
    utm_x             REAL,
    utm_y             REAL,
    orden             INTEGER,
    revisada          INTEGER NOT NULL DEFAULT 0,
    incluir           INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS revisiones (
    id             INTEGER PRIMARY KEY,
    documento_id   INTEGER NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
    fecha          TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    usuario        TEXT,
    ict            REAL NOT NULL,
    subindices     TEXT NOT NULL,
    interpretacion TEXT,
    resumen        TEXT,
    fortalezas     TEXT,
    usa_ia         INTEGER NOT NULL DEFAULT 0,
    modelo         TEXT,
    aviso          TEXT
);
CREATE TABLE IF NOT EXISTS hallazgos (
    id                    INTEGER PRIMARY KEY,
    revision_id           INTEGER NOT NULL REFERENCES revisiones(id) ON DELETE CASCADE,
    origen                TEXT NOT NULL,
    categoria             TEXT NOT NULL,
    criticidad            TEXT NOT NULL,
    ubicacion             TEXT,
    descripcion           TEXT NOT NULL,
    evidencia             TEXT,
    riesgo                TEXT,
    recomendacion         TEXT,
    referencia            TEXT,
    evidencia_localizada  INTEGER,
    estado                TEXT NOT NULL DEFAULT 'abierto',
    nota                  TEXT
);
CREATE TABLE IF NOT EXISTS medio_fisico (
    campo       TEXT PRIMARY KEY,
    valor       TEXT,
    fuente      TEXT,
    observacion TEXT,
    actualizado TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS analisis_dispersion (
    id                  INTEGER PRIMARY KEY,
    fecha               TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    usuario             TEXT,
    metricas            TEXT NOT NULL,
    capitulo            TEXT NOT NULL,
    usa_ia              INTEGER NOT NULL DEFAULT 0,
    modelo              TEXT,
    aviso               TEXT,
    cifras_no_respaldadas TEXT
);
CREATE TABLE IF NOT EXISTS bitacora (
    id        INTEGER PRIMARY KEY,
    fecha     TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    usuario   TEXT,
    entidad   TEXT NOT NULL,
    referencia TEXT,
    accion    TEXT NOT NULL,
    antes     TEXT,
    despues   TEXT
);
"""


def raiz_trabajo() -> Path:
    """Directorio raíz de espacios de trabajo (configurable con CAEPSA_WORKSPACE)."""
    raiz = Path(os.environ.get("CAEPSA_WORKSPACE", Path.cwd() / "workspace"))
    raiz.mkdir(parents=True, exist_ok=True)
    return raiz


def conectar(ruta: Path, esquema: str) -> sqlite3.Connection:
    con = sqlite3.connect(ruta)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(esquema)
    return con


def registro() -> sqlite3.Connection:
    return conectar(raiz_trabajo() / "hub.db", ESQUEMA_REGISTRO)
