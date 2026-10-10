"""Datos del medio físico del sitio, cada uno con su fuente documental.

El análisis de dispersión solo usa datos capturados aquí con fuente (levantamiento de campo, carta temática,
estación climatológica, informe de laboratorio…). Un dato sin fuente se reporta como pendiente.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..proyectos import Proyecto

RUMBOS = ("N", "NE", "E", "SE", "S", "SO", "O", "NO")
AZIMUT = {r: i * 45.0 for i, r in enumerate(RUMBOS)}

TEXTURAS = ("arena", "arena franca", "franco arenoso", "franco", "franco limoso", "limo", "franco arcillo arenoso",
            "franco arcilloso", "franco arcillo limoso", "arcilla arenosa", "arcilla limosa", "arcilla")

@dataclass(frozen=True)
class Campo:
    clave: str
    grupo: str
    etiqueta: str
    tipo: str = "texto"  # "texto" | "numero" | "opcion"
    unidad: str = ""
    opciones: tuple[str, ...] = ()
    requerido: bool = False
    minimo: float | None = None
    maximo: float | None = None


CAMPOS: tuple[Campo, ...] = (
    Campo("origen_x", "Evento", "Origen del derrame, X (UTM)", "numero", "m", requerido=True,
          minimo=100_000, maximo=900_000),
    Campo("origen_y", "Evento", "Origen del derrame, Y (UTM)", "numero", "m", requerido=True,
          minimo=1_000_000, maximo=3_700_000),
    Campo("volumen_derramado_l", "Evento", "Volumen derramado", "numero", "L", requerido=True, minimo=0),
    Campo("acciones_contencion", "Evento", "Acciones de contención realizadas"),
    Campo("elevacion_msnm", "Topografía", "Elevación", "numero", "m s.n.m."),
    Campo("pendiente_pct", "Topografía", "Pendiente del terreno", "numero", "%", requerido=True, minimo=0, maximo=100),
    Campo("direccion_pendiente", "Topografía", "Dirección de la pendiente (hacia donde desciende)", "opcion",
          opciones=RUMBOS, requerido=True),
    Campo("relieve", "Topografía", "Relieve", "opcion",
          opciones=("plano", "lomerío suave", "ladera", "cauce o depresión")),
    Campo("textura", "Suelo", "Textura del suelo", "opcion", opciones=TEXTURAS, requerido=True),
    Campo("tipo_suelo", "Suelo", "Tipo de suelo (clasificación edafológica)"),
    Campo("conductividad_hidraulica_cm_s", "Suelo", "Conductividad hidráulica", "numero", "cm/s", minimo=0),
    Campo("porosidad_efectiva", "Suelo", "Porosidad efectiva", "numero", "fracción", minimo=0, maximo=1),
    Campo("materia_organica_pct", "Suelo", "Materia orgánica", "numero", "%", minimo=0, maximo=100),
    Campo("unidad_geologica", "Geología", "Unidad geológica", requerido=True),
    Campo("fracturamiento", "Geología", "Fracturamiento", "opcion", opciones=("no observado", "moderado", "intenso")),
    Campo("profundidad_roca_m", "Geología", "Profundidad a roca", "numero", "m", minimo=0),
    Campo("tipo_cuerpo_agua", "Hidrología superficial", "Cuerpo de agua más cercano (tipo)", "opcion",
          opciones=("río perenne", "río intermitente", "canal de riego", "lago o laguna", "presa o bordo",
                    "ninguno identificado"), requerido=True),
    Campo("cuerpo_agua", "Hidrología superficial", "Nombre del cuerpo de agua"),
    Campo("distancia_cuerpo_agua_m", "Hidrología superficial", "Distancia al cuerpo de agua", "numero", "m", minimo=0),
    Campo("direccion_cuerpo_agua", "Hidrología superficial", "Dirección del cuerpo de agua desde el sitio", "opcion",
          opciones=RUMBOS),
    Campo("profundidad_nivel_freatico_m", "Hidrología subterránea", "Profundidad al nivel freático", "numero", "m",
          requerido=True, minimo=0),
    Campo("direccion_flujo_subterraneo", "Hidrología subterránea", "Dirección del flujo subterráneo", "opcion",
          opciones=RUMBOS),
    Campo("acuifero", "Hidrología subterránea", "Acuífero"),
    Campo("distancia_pozo_m", "Hidrología subterránea", "Distancia al pozo de agua más cercano", "numero", "m",
          minimo=0),
    Campo("cobertura_vegetal", "Vegetación y uso", "Cobertura vegetal / cultivos", requerido=True),
    Campo("uso_actual", "Vegetación y uso", "Uso actual del predio"),
    Campo("precipitacion_anual_mm", "Clima", "Precipitación media anual", "numero", "mm", requerido=True,
          minimo=0, maximo=6000),
    Campo("meses_lluvia", "Clima", "Temporada de lluvias"),
    Campo("temperatura_media_c", "Clima", "Temperatura media anual", "numero", "°C", minimo=-10, maximo=45),
    Campo("estacion_climatologica", "Clima", "Estación climatológica de referencia"),
)
POR_CLAVE = {c.clave: c for c in CAMPOS}
GRUPOS = tuple(dict.fromkeys(c.grupo for c in CAMPOS))


def validar(clave: str, valor: Any) -> Any:
    c = POR_CLAVE.get(clave)
    if c is None:
        raise ValueError(f"Campo desconocido del medio físico: {clave}")
    if valor is None or str(valor).strip() == "":
        return None
    if c.tipo == "numero":
        try:
            v = float(str(valor).replace(",", ""))
        except ValueError as e:
            raise ValueError(f"{c.etiqueta}: «{valor}» no es un número") from e
        if (c.minimo is not None and v < c.minimo) or (c.maximo is not None and v > c.maximo):
            raise ValueError(f"{c.etiqueta}: {v:g} fuera del rango admisible ({c.minimo:g}–{c.maximo:g} {c.unidad})"
                             if c.maximo is not None else f"{c.etiqueta}: {v:g} debe ser ≥ {c.minimo:g}")
        return v
    if c.tipo == "opcion" and str(valor) not in c.opciones:
        raise ValueError(f"{c.etiqueta}: «{valor}» no es una opción válida ({', '.join(c.opciones)})")
    return str(valor).strip()


def guardar(p: Proyecto, datos: dict[str, dict[str, Any]]) -> list[str]:
    """Guarda {campo: {valor, fuente, observacion}}. Devuelve los campos modificados."""
    limpios = {k: (validar(k, d.get("valor")), (d.get("fuente") or "").strip() or None,
                   (d.get("observacion") or "").strip() or None) for k, d in datos.items()}
    actuales = leer(p)
    cambiados = []
    with p.con:
        for k, (valor, fuente, obs) in limpios.items():
            previo = actuales.get(k, {})
            if (previo.get("valor"), previo.get("fuente"), previo.get("observacion")) == (valor, fuente, obs):
                continue
            p.con.execute(
                "INSERT INTO medio_fisico (campo, valor, fuente, observacion) VALUES (?,?,?,?) "
                "ON CONFLICT(campo) DO UPDATE SET valor=excluded.valor, fuente=excluded.fuente, "
                "observacion=excluded.observacion, actualizado=datetime('now','localtime')",
                (k, json.dumps(valor, ensure_ascii=False), fuente, obs))
            p.registrar_cambio("medio_fisico", k, "actualizar", previo or None,
                               {"valor": valor, "fuente": fuente, "observacion": obs})
            cambiados.append(k)
    return cambiados


def leer(p: Proyecto) -> dict[str, dict[str, Any]]:
    return {f["campo"]: {"valor": json.loads(f["valor"]) if f["valor"] is not None else None,
                         "fuente": f["fuente"], "observacion": f["observacion"], "actualizado": f["actualizado"]}
            for f in p.con.execute("SELECT * FROM medio_fisico")}


def valor(datos: dict[str, dict[str, Any]], clave: str) -> Any:
    """Valor utilizable: solo si tiene fuente documentada."""
    d = datos.get(clave) or {}
    return d.get("valor") if d.get("fuente") else None


def faltantes(datos: dict[str, dict[str, Any]]) -> dict[str, list[Campo]]:
    """Campos requeridos sin valor y campos con valor pero sin fuente."""
    sin_valor = [c for c in CAMPOS if c.requerido and (datos.get(c.clave) or {}).get("valor") is None]
    sin_fuente = [c for c in CAMPOS if (datos.get(c.clave) or {}).get("valor") is not None
                  and not (datos.get(c.clave) or {}).get("fuente")]
    return {"sin_valor": sin_valor, "sin_fuente": sin_fuente}
