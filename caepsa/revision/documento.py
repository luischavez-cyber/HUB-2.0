"""Lectura del borrador del informe (.docx o .pdf) en bloques con su ubicación."""
from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

_RE_TITULO_NUMERADO = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+([A-ZÁÉÍÓÚÑ][^\n]{2,90})$")
_RE_TITULO_MAYUS = re.compile(r"^[A-ZÁÉÍÓÚÑ0-9 .,()/-]{6,90}$")


@dataclass
class Bloque:
    tipo: str  # "titulo" | "parrafo" | "tabla"
    texto: str
    seccion: str
    ubicacion: str
    filas: list[list[str]] = field(default_factory=list)


@dataclass
class Documento:
    nombre: str
    bloques: list[Bloque]
    paginas: int | None = None

    @property
    def titulos(self) -> list[Bloque]:
        return [b for b in self.bloques if b.tipo == "titulo"]

    @property
    def tablas(self) -> list[Bloque]:
        return [b for b in self.bloques if b.tipo == "tabla"]

    @property
    def texto(self) -> str:
        """Texto corrido (párrafos y títulos), sin tablas."""
        return "\n".join(b.texto for b in self.bloques if b.tipo != "tabla")

    def como_texto_marcado(self) -> str:
        """Representación para el revisor: títulos, párrafos y tablas con su ubicación."""
        partes = []
        for b in self.bloques:
            if b.tipo == "titulo":
                partes.append(f"\n## {b.texto}  [{b.ubicacion}]")
            elif b.tipo == "tabla":
                filas = [" | ".join(c or "" for c in f) for f in b.filas]
                partes.append(f"[{b.ubicacion}]\n" + "\n".join(filas))
            else:
                partes.append(f"{b.texto}  [{b.ubicacion}]")
        return "\n".join(partes)


def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos ni espacios repetidos: para comparar citas."""
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[“”«»\"']", "", t)
    return " ".join(t.split())


def _es_titulo(linea: str) -> bool:
    linea = linea.strip()
    if not linea or len(linea) > 90 or linea.endswith((".", ",", ";", ":")):
        return False
    if _RE_TITULO_NUMERADO.match(linea):
        return True
    return bool(_RE_TITULO_MAYUS.match(linea)) and sum(c.isalpha() for c in linea) >= 5


def _celdas(fila: list[object]) -> list[str]:
    return [" ".join(str(c).split()) if c is not None else "" for c in fila]


def leer_docx(contenido: bytes, nombre: str = "borrador.docx") -> Documento:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(io.BytesIO(contenido))
    bloques: list[Bloque] = []
    seccion = "(inicio)"
    n_par = n_tab = 0
    for el in doc.element.body.iterchildren():
        etiqueta = el.tag.rsplit("}", 1)[-1]
        if etiqueta == "p":
            par = Paragraph(el, doc)
            texto = " ".join(par.text.split())
            if not texto:
                continue
            n_par += 1
            estilo = (par.style.name if par.style is not None else "") or ""
            es_titulo = estilo.lower().startswith(("heading", "título", "titulo", "title")) or (
                _es_titulo(texto) and len(texto.split()) <= 12)
            if es_titulo:
                seccion = texto
                bloques.append(Bloque("titulo", texto, seccion, f"párr. {n_par}"))
            else:
                bloques.append(Bloque("parrafo", texto, seccion, f"párr. {n_par}"))
        elif etiqueta == "tbl":
            n_tab += 1
            tabla = Table(el, doc)
            filas = []
            for fila in tabla.rows:
                celdas, previa = [], None
                for c in fila.cells:  # celdas combinadas se repiten en python-docx
                    if c._tc is previa:
                        continue
                    previa = c._tc
                    celdas.append(" ".join(c.text.split()))
                filas.append(celdas)
            texto = "\n".join(" | ".join(f) for f in filas)
            bloques.append(Bloque("tabla", texto, seccion, f"Tabla {n_tab} (sección «{seccion}»)", filas))
    return Documento(nombre, bloques)


def leer_pdf(contenido: bytes, nombre: str = "borrador.pdf") -> Documento:
    import pdfplumber

    bloques: list[Bloque] = []
    seccion = "(inicio)"
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        paginas = len(pdf.pages)
        n_tab = 0
        for num, pagina in enumerate(pdf.pages, start=1):
            tablas = pagina.find_tables()
            # Texto fuera de las tablas, para no duplicar su contenido.
            fuera = pagina
            for t in tablas:
                fuera = fuera.outside_bbox(t.bbox)
            for linea in (fuera.extract_text() or "").splitlines():
                linea = " ".join(linea.split())
                if not linea:
                    continue
                if _es_titulo(linea):
                    seccion = linea
                    bloques.append(Bloque("titulo", linea, seccion, f"p. {num}"))
                else:
                    bloques.append(Bloque("parrafo", linea, seccion, f"p. {num}"))
            for t in tablas:
                n_tab += 1
                filas = [_celdas(f) for f in t.extract()]
                bloques.append(Bloque("tabla", "\n".join(" | ".join(f) for f in filas), seccion,
                                      f"Tabla {n_tab}, p. {num}", filas))
    return Documento(nombre, _unir_parrafos(bloques), paginas)


def _unir_parrafos(bloques: list[Bloque]) -> list[Bloque]:
    """En PDF cada línea llega por separado: une líneas consecutivas de la misma página y sección."""
    salida: list[Bloque] = []
    for b in bloques:
        previo = salida[-1] if salida else None
        if (b.tipo == "parrafo" and previo and previo.tipo == "parrafo" and previo.ubicacion == b.ubicacion
                and previo.seccion == b.seccion and not previo.texto.endswith((".", ":"))):
            previo.texto = f"{previo.texto} {b.texto}"
        else:
            salida.append(b)
    return salida


def leer(ruta_o_bytes: Path | bytes, nombre: str | None = None) -> Documento:
    if isinstance(ruta_o_bytes, Path):
        nombre = nombre or ruta_o_bytes.name
        contenido = ruta_o_bytes.read_bytes()
    else:
        contenido = ruta_o_bytes
    nombre = nombre or "borrador"
    if contenido[:4] == b"%PDF":
        return leer_pdf(contenido, nombre)
    if contenido[:2] == b"PK":
        return leer_docx(contenido, nombre)
    raise ValueError("Formato no soportado: suba el borrador en .docx o .pdf")
