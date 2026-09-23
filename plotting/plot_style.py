from __future__ import annotations

BLUE = "#2a78d6"
ORANGE = "#eb6834"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
INK = "#0b0b0b"
MUTED = "#898781"


def style_axes(plt, font_size: int = 10) -> None:
    plt.rcParams.update({
        "figure.facecolor": "#fcfcfb",
        "axes.facecolor": "#fcfcfb",
        "axes.edgecolor": AXIS,
        "axes.labelcolor": INK,
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "text.color": INK,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "font.size": font_size,
    })
