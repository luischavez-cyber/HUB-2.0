"""Figura 5.1: plano de distribución de la afectación (PNG para el informe impreso).

La excedencia se distingue por forma (triángulo relleno vs círculo hueco), etiqueta y leyenda, no solo por color.
"""
from __future__ import annotations

import io
import math
from typing import Any

from . import medio_fisico as mf

SUPERFICIE = "#fcfcfb"
TINTA = "#0b0b0b"
TINTA_SECUNDARIA = "#3d3d3a"
NEUTRO = "#5f5f5c"
REJILLA = "#e6e6e3"
CRITICO = "#d03b3b"  # estado crítico: excede LMP


def plano(analisis: dict[str, Any]) -> bytes | None:
    """PNG del plano o None si no hay puntos con coordenadas."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Polygon
    from matplotlib.ticker import ScalarFormatter

    puntos = [x for x in analisis.get("puntos", []) if x["x"] is not None and x["y"] is not None]
    if not puntos:
        return None
    xs, ys = [x["x"] for x in puntos], [x["y"] for x in puntos]
    origen = analisis.get("origen")
    if origen:
        xs.append(origen["x"])
        ys.append(origen["y"])
    extension = max(max(xs) - min(xs), max(ys) - min(ys), 20.0)
    margen = extension * 0.15

    fig, ax = plt.subplots(figsize=(7.0, 7.0), dpi=200)
    fig.patch.set_facecolor(SUPERFICIE)
    ax.set_facecolor(SUPERFICIE)
    leyenda: list[Any] = []

    env = analisis.get("espacial", {}).get("envolvente")
    if env:
        ax.add_patch(Polygon(env, closed=True, facecolor=CRITICO, alpha=0.12, edgecolor=CRITICO, linewidth=1.5,
                             zorder=1))
        leyenda.append(Polygon([[0, 0]], facecolor=CRITICO, alpha=0.25, edgecolor=CRITICO,
                               label="Envolvente de puntos con excedencia"))

    for x in puntos:
        if x["excede"]:
            ax.plot(x["x"], x["y"], marker="^", markersize=9, color=CRITICO, markeredgecolor=SUPERFICIE,
                    markeredgewidth=1, linestyle="none", zorder=4)
        else:
            ax.plot(x["x"], x["y"], marker="o", markersize=8, markerfacecolor=SUPERFICIE, markeredgecolor=NEUTRO,
                    markeredgewidth=1.5, linestyle="none", zorder=3)
        ax.annotate(x["punto"], (x["x"], x["y"]), xytext=(5, 4), textcoords="offset points", fontsize=7,
                    color=TINTA_SECUNDARIA, zorder=5)
    leyenda += [
        Line2D([], [], marker="^", markersize=9, color=CRITICO, linestyle="none", label="Excede LMP (NOM-138)"),
        Line2D([], [], marker="o", markersize=8, markerfacecolor=SUPERFICIE, markeredgecolor=NEUTRO,
               markeredgewidth=1.5, linestyle="none", label="No excede LMP"),
    ]

    if origen:
        # Estrella hueca: deja ver si el punto bajo el origen excede.
        ax.plot(origen["x"], origen["y"], marker="*", markersize=20, markerfacecolor="none", markeredgecolor=TINTA,
                markeredgewidth=1.5, linestyle="none", zorder=6)
        etiqueta = "Origen del derrame" if origen["tipo"] == "documentado" else "Punto de mayor concentración"
        leyenda.append(Line2D([], [], marker="*", markersize=14, markerfacecolor="none", markeredgecolor=TINTA,
                              markeredgewidth=1.5, linestyle="none", label=etiqueta))
        largo = extension * 0.3

        def flecha(az: float, estilo: str, color: str, texto: str) -> None:
            dx, dy = largo * math.sin(math.radians(az)), largo * math.cos(math.radians(az))
            ax.annotate("", xy=(origen["x"] + dx, origen["y"] + dy), xytext=(origen["x"], origen["y"]),
                        arrowprops={"arrowstyle": "-|>", "color": color, "linewidth": 2, "linestyle": estilo,
                                    "mutation_scale": 14}, zorder=2)
            leyenda.append(Line2D([], [], color=color, linewidth=2, linestyle=estilo, label=texto))

        mfis = analisis.get("medio_fisico", {})
        if "direccion_pendiente" in mfis:
            r = mfis["direccion_pendiente"]["valor"]
            flecha(mf.AZIMUT[r], "solid", NEUTRO, f"Pendiente del terreno ({r})")
        if "direccion_flujo_subterraneo" in mfis:
            r = mfis["direccion_flujo_subterraneo"]["valor"]
            flecha(mf.AZIMUT[r], "dotted", NEUTRO, f"Flujo subterráneo ({r})")
        disp = analisis.get("espacial", {}).get("direccion_dispersion")
        if disp:
            flecha(disp["azimut"], "dashed", TINTA, f"Dirección de dispersión observada ({disp['rumbo']})")

    ax.set_xlim(min(xs) - margen, max(xs) + margen)
    ax.set_ylim(min(ys) - margen, max(ys) + margen)
    ax.set_aspect("equal", adjustable="box")
    for eje in (ax.xaxis, ax.yaxis):
        fmt = ScalarFormatter(useOffset=False)
        fmt.set_scientific(False)
        eje.set_major_formatter(fmt)
    ax.tick_params(labelsize=7, colors=TINTA_SECUNDARIA)
    ax.set_xlabel("X UTM (m)", fontsize=8, color=TINTA_SECUNDARIA)
    ax.set_ylabel("Y UTM (m)", fontsize=8, color=TINTA_SECUNDARIA)
    ax.grid(color=REJILLA, linewidth=0.5)
    for borde in ax.spines.values():
        borde.set_color(REJILLA)
    ax.annotate("N", xy=(0.96, 0.16), xytext=(0.96, 0.05), xycoords="axes fraction", ha="center", va="center",
                fontsize=9, fontweight="bold", color=TINTA,
                arrowprops={"arrowstyle": "-|>", "color": TINTA, "linewidth": 1.5})
    # Leyenda fuera del área de datos para no ocultar puntos.
    ax.legend(handles=leyenda, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2, fontsize=7,
              frameon=False)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=SUPERFICIE)
    plt.close(fig)
    return buf.getvalue()
