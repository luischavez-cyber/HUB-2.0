"""Módulo 1 — Gestión de Proyectos.

Cada proyecto tiene su propio espacio de trabajo::

    workspace/proyectos/<clave>/
        proyecto.db      base de datos del proyecto (ficha, muestras, resultados, bitácora)
        archivos/        documentos cargados (PDF de laboratorio, fotos, borradores)
        versiones/       instantáneas de la base de datos (control de versiones)

El registro central (``workspace/hub.db``) indexa todos los proyectos.
Todo cambio a la ficha, muestras o resultados queda en la bitácora con su
valor anterior y nuevo (trazabilidad).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from . import db
from .normativa.nom138 import PRODUCTOS, UsoSuelo


@dataclass(frozen=True)
class Campo:
    clave: str
    etiqueta: str
    requerido: bool = True


CAMPOS_FICHA: tuple[Campo, ...] = (
    Campo("nombre", "Nombre del proyecto"),
    Campo("cliente", "Cliente"),
    Campo("sitio", "Sitio"),
    Campo("municipio", "Municipio"),
    Campo("estado", "Estado"),
    Campo("ubicacion", "Ubicación de referencia (km, vía, predio)"),
    Campo("producto", "Tipo de contaminante (Tabla 1 NOM-138)"),
    Campo("usos_suelo", "Uso(s) de suelo"),
    Campo("responsable_tecnico", "Responsable técnico"),
    Campo("expediente", "Número de expediente"),
    Campo("fecha_evento", "Fecha del evento", requerido=False),
    Campo("laboratorio", "Laboratorio acreditado", requerido=False),
    Campo("acreditacion_laboratorio", "Acreditación del laboratorio (organismo y número)", requerido=False),
    Campo("utm_zona", "Zona UTM del sitio", requerido=False),
    Campo("zonas", "Zonas de muestreo (separadas por coma)", requerido=False),
    Campo("puntos_esperados", "Puntos de muestreo esperados", requerido=False),
    Campo("muestras_esperadas", "Muestras esperadas", requerido=False),
)

ZONAS_PREDETERMINADAS = "Zona 1, Zona 2, Zona 3, Periferia"


def _slug(texto: str) -> str:
    import unicodedata

    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:60] or "proyecto"


class Proyecto:
    """Acceso a un proyecto y su espacio de trabajo."""

    def __init__(self, clave: str, ruta: Path, usuario: str = "sistema"):
        self.clave = clave
        self.ruta = ruta
        self.usuario = usuario
        (ruta / "archivos").mkdir(parents=True, exist_ok=True)
        (ruta / "versiones").mkdir(exist_ok=True)
        self.con: sqlite3.Connection = db.conectar(ruta / "proyecto.db", db.ESQUEMA_PROYECTO)

    # ------------------------------------------------------------------ registro
    @classmethod
    def crear(cls, nombre: str, usuario: str = "sistema", **ficha: Any) -> "Proyecto":
        base = _slug(nombre)
        reg = db.registro()
        clave, n = base, 1
        while reg.execute("SELECT 1 FROM proyectos WHERE clave=?", (clave,)).fetchone():
            n += 1
            clave = f"{base}-{n}"
        ruta = db.raiz_trabajo() / "proyectos" / clave
        reg.execute("INSERT INTO proyectos (clave, nombre, ruta) VALUES (?,?,?)", (clave, nombre, str(ruta)))
        reg.commit()
        p = cls(clave, ruta, usuario)
        p.actualizar_ficha({"nombre": nombre, "zonas": ZONAS_PREDETERMINADAS, **ficha})
        return p

    @classmethod
    def abrir(cls, clave: str, usuario: str = "sistema") -> "Proyecto":
        fila = db.registro().execute("SELECT ruta FROM proyectos WHERE clave=?", (clave,)).fetchone()
        if not fila:
            raise KeyError(f"Proyecto no registrado: {clave}")
        return cls(clave, Path(fila["ruta"]), usuario)

    @staticmethod
    def listar() -> list[dict[str, Any]]:
        filas = db.registro().execute("SELECT * FROM proyectos ORDER BY actualizado DESC").fetchall()
        return [dict(f) for f in filas]

    def _tocar(self) -> None:
        reg = db.registro()
        reg.execute(
            "UPDATE proyectos SET actualizado=datetime('now','localtime'), nombre=? WHERE clave=?",
            (self.ficha().get("nombre") or self.clave, self.clave),
        )
        reg.commit()

    # ------------------------------------------------------------------ bitácora
    def registrar_cambio(self, entidad: str, referencia: str, accion: str, antes: Any, despues: Any) -> None:
        self.con.execute(
            "INSERT INTO bitacora (usuario, entidad, referencia, accion, antes, despues) VALUES (?,?,?,?,?,?)",
            (
                self.usuario,
                entidad,
                referencia,
                accion,
                None if antes is None else json.dumps(antes, ensure_ascii=False, default=str),
                None if despues is None else json.dumps(despues, ensure_ascii=False, default=str),
            ),
        )

    def bitacora(self, limite: int = 500) -> list[dict[str, Any]]:
        q = "SELECT * FROM bitacora ORDER BY id DESC LIMIT ?"
        return [dict(f) for f in self.con.execute(q, (limite,))]

    # ------------------------------------------------------------------ ficha
    def ficha(self) -> dict[str, Any]:
        datos: dict[str, Any] = {}
        for f in self.con.execute("SELECT campo, valor FROM ficha"):
            datos[f["campo"]] = json.loads(f["valor"]) if f["valor"] is not None else None
        return datos

    def actualizar_ficha(self, cambios: dict[str, Any]) -> None:
        if "producto" in cambios and cambios["producto"] and cambios["producto"] not in PRODUCTOS:
            raise ValueError(f"Producto no contemplado en la Tabla 1 de la NOM-138: {cambios['producto']}")
        if "usos_suelo" in cambios and cambios["usos_suelo"] is not None:
            cambios["usos_suelo"] = [UsoSuelo(u).value for u in cambios["usos_suelo"]]
        actual = self.ficha()
        with self.con:
            for campo, valor in cambios.items():
                if actual.get(campo) == valor:
                    continue
                self.con.execute(
                    "INSERT INTO ficha (campo, valor) VALUES (?,?) "
                    "ON CONFLICT(campo) DO UPDATE SET valor=excluded.valor",
                    (campo, json.dumps(valor, ensure_ascii=False)),
                )
                self.registrar_cambio("ficha", campo, "actualizar", actual.get(campo), valor)
        self._tocar()

    def usos_suelo(self) -> list[UsoSuelo]:
        return [UsoSuelo(u) for u in (self.ficha().get("usos_suelo") or [])]

    def zonas(self) -> list[str]:
        texto = self.ficha().get("zonas") or ZONAS_PREDETERMINADAS
        return [z.strip() for z in str(texto).split(",") if z.strip()]

    # ------------------------------------------------------------------ documentos
    def guardar_documento(self, tipo: str, nombre: str, contenido: bytes) -> Path:
        sha = hashlib.sha256(contenido).hexdigest()
        destino = self.ruta / "archivos" / tipo / f"{sha[:10]}_{Path(nombre).name}"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(contenido)
        with self.con:
            self.con.execute(
                "INSERT INTO documentos (tipo, nombre, ruta, sha256) VALUES (?,?,?,?)",
                (tipo, nombre, str(destino), sha),
            )
            self.registrar_cambio("documento", nombre, "cargar", None, {"tipo": tipo, "sha256": sha})
        self._tocar()
        return destino

    def documentos(self, tipo: str | None = None) -> list[dict[str, Any]]:
        if tipo:
            filas = self.con.execute("SELECT * FROM documentos WHERE tipo=? ORDER BY id DESC", (tipo,))
        else:
            filas = self.con.execute("SELECT * FROM documentos ORDER BY id DESC")
        return [dict(f) for f in filas]

    # ------------------------------------------------------------------ muestras y resultados
    def guardar_punto(self, clave: str, **datos: Any) -> int:
        previo = self.con.execute("SELECT * FROM puntos WHERE clave=?", (clave,)).fetchone()
        campos = {k: v for k, v in datos.items() if k in ("zona", "utm_x", "utm_y", "utm_zona", "descripcion")}
        with self.con:
            if previo:
                nuevos = {k: v for k, v in campos.items() if v is not None and previo[k] != v}
                if nuevos:
                    sets = ", ".join(f"{k}=?" for k in nuevos)
                    self.con.execute(f"UPDATE puntos SET {sets} WHERE id=?", (*nuevos.values(), previo["id"]))
                    self.registrar_cambio("punto", clave, "actualizar", {k: previo[k] for k in nuevos}, nuevos)
                return int(previo["id"])
            cur = self.con.execute(
                "INSERT INTO puntos (clave, zona, utm_x, utm_y, utm_zona, descripcion) VALUES (?,?,?,?,?,?)",
                (clave, campos.get("zona"), campos.get("utm_x"), campos.get("utm_y"),
                 campos.get("utm_zona"), campos.get("descripcion")),
            )
            self.registrar_cambio("punto", clave, "crear", None, campos)
            return int(cur.lastrowid or 0)

    def guardar_muestra(self, clave: str, punto: str | None, **datos: Any) -> int:
        punto_id = self.guardar_punto(punto) if punto else None
        campos = {k: v for k, v in datos.items()
                  if k in ("profundidad_m", "fecha_muestreo", "folio_lab", "origen", "pagina_pdf")}
        if punto_id is not None:
            campos["punto_id"] = punto_id
        previo = self.con.execute("SELECT * FROM muestras WHERE clave=?", (clave,)).fetchone()
        with self.con:
            if previo:
                nuevos = {k: v for k, v in campos.items() if v is not None and previo[k] != v}
                if nuevos:
                    sets = ", ".join(f"{k}=?" for k in nuevos)
                    self.con.execute(f"UPDATE muestras SET {sets} WHERE id=?", (*nuevos.values(), previo["id"]))
                    self.registrar_cambio("muestra", clave, "actualizar", {k: previo[k] for k in nuevos}, nuevos)
                return int(previo["id"])
            cols = ["clave", *campos]
            cur = self.con.execute(
                f"INSERT INTO muestras ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                (clave, *campos.values()),
            )
            self.registrar_cambio("muestra", clave, "crear", None, campos)
            return int(cur.lastrowid or 0)

    def guardar_resultado(self, muestra: str, parametro: str, valor: float | None, *,
                          menor_que: bool = False, limite_deteccion: float | None = None,
                          unidad: str | None = None, metodo: str | None = None,
                          origen: str = "manual", pagina_pdf: int | None = None) -> None:
        fila = self.con.execute("SELECT id FROM muestras WHERE clave=?", (muestra,)).fetchone()
        if not fila:
            raise KeyError(f"Muestra inexistente: {muestra}")
        nuevo = {"valor": valor, "menor_que": int(menor_que), "limite_deteccion": limite_deteccion,
                 "unidad": unidad, "metodo": metodo, "origen": origen, "pagina_pdf": pagina_pdf}
        previo = self.con.execute(
            "SELECT valor, menor_que, limite_deteccion, unidad, metodo, origen, pagina_pdf "
            "FROM resultados WHERE muestra_id=? AND parametro=?", (fila["id"], parametro)).fetchone()
        if previo and dict(previo) == nuevo:
            return
        with self.con:
            self.con.execute(
                "INSERT INTO resultados (muestra_id, parametro, valor, menor_que, limite_deteccion, unidad,"
                " metodo, origen, pagina_pdf) VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(muestra_id, parametro) DO UPDATE SET valor=excluded.valor,"
                " menor_que=excluded.menor_que, limite_deteccion=excluded.limite_deteccion,"
                " unidad=excluded.unidad, metodo=excluded.metodo, origen=excluded.origen,"
                " pagina_pdf=excluded.pagina_pdf",
                (fila["id"], parametro, *nuevo.values()),
            )
            self.registrar_cambio("resultado", f"{muestra}/{parametro}", "actualizar" if previo else "crear",
                           dict(previo) if previo else None, nuevo)
        self._tocar()

    def eliminar_muestra(self, clave: str) -> None:
        previo = self.con.execute("SELECT * FROM muestras WHERE clave=?", (clave,)).fetchone()
        if not previo:
            return
        with self.con:
            self.con.execute("DELETE FROM muestras WHERE id=?", (previo["id"],))
            self.registrar_cambio("muestra", clave, "eliminar", dict(previo), None)
        self._tocar()

    def tabla_resultados(self) -> list[dict[str, Any]]:
        """Vista plana: una fila por resultado con datos de muestra y punto."""
        q = """
        SELECT m.clave AS muestra, p.clave AS punto, p.zona, p.utm_x, p.utm_y, p.utm_zona,
               m.profundidad_m, m.fecha_muestreo, m.folio_lab, r.parametro, r.valor, r.menor_que,
               r.limite_deteccion, r.unidad, r.metodo, r.origen, r.pagina_pdf
        FROM muestras m
        LEFT JOIN puntos p ON p.id = m.punto_id
        LEFT JOIN resultados r ON r.muestra_id = m.id
        ORDER BY p.zona, p.clave, m.clave, r.parametro
        """
        return [dict(f) for f in self.con.execute(q)]

    def conteos(self) -> dict[str, int]:
        uno = lambda q: int(self.con.execute(q).fetchone()[0])  # noqa: E731
        return {
            "puntos": uno("SELECT COUNT(*) FROM puntos"),
            "muestras": uno("SELECT COUNT(*) FROM muestras"),
            "resultados": uno("SELECT COUNT(*) FROM resultados"),
            "documentos": uno("SELECT COUNT(*) FROM documentos"),
        }

    # ------------------------------------------------------------------ versiones
    def crear_instantanea(self, etiqueta: str) -> Path:
        """Copia consistente de la base del proyecto (control de versiones)."""
        marca = datetime.now().strftime("%Y%m%d-%H%M%S")
        destino = self.ruta / "versiones" / f"{marca}_{_slug(etiqueta)}.db"
        with sqlite3.connect(destino) as copia:
            self.con.backup(copia)
        with self.con:
            self.registrar_cambio("version", destino.name, "instantanea", None, {"etiqueta": etiqueta})
        return destino

    def versiones(self) -> list[Path]:
        return sorted((self.ruta / "versiones").glob("*.db"), reverse=True)

    def restaurar_instantanea(self, archivo: Path) -> None:
        self.crear_instantanea("respaldo previo a restauracion")
        with sqlite3.connect(archivo) as origen:
            origen.backup(self.con)
        with self.con:
            self.registrar_cambio("version", archivo.name, "restaurar", None, {"archivo": archivo.name})

    def cerrar(self) -> None:
        self.con.close()


def campos_faltantes(ficha: dict[str, Any], campos: Iterable[Campo] = CAMPOS_FICHA) -> list[Campo]:
    return [c for c in campos if c.requerido and not ficha.get(c.clave)]


def borrar_espacio(clave: str) -> None:
    """Elimina un proyecto del registro y su carpeta (irreversible)."""
    reg = db.registro()
    fila = reg.execute("SELECT ruta FROM proyectos WHERE clave=?", (clave,)).fetchone()
    if fila:
        shutil.rmtree(fila["ruta"], ignore_errors=True)
        reg.execute("DELETE FROM proyectos WHERE clave=?", (clave,))
        reg.commit()
