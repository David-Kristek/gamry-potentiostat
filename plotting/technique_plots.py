"""
technique_plots.py
------------------
One stateless `TechniquePlotter` per technique: it draws the initial
curve(s) into axes it is handed (`plot_data`, shared by the live dashboard
and the saved PNG) and repaints those lines from raw `acq_data()` during a
run (`update_lines`). The owning `Technique` subclass points at its plotter
via `Technique.plotter`; there is no separate plotter registry.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

import numpy as np

from potentiostat.plotting.plot_style import BLUE, ORANGE

if TYPE_CHECKING:
    import pandas as pd
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure
    from matplotlib.lines import Line2D


class TechniquePlotter(ABC):
    """Stateless visualizer. All classmethods -- never instantiated."""

    n_axes: ClassVar[int] = 1
    figsize: ClassVar[tuple[float, float]] = (7, 4)

    @classmethod
    def figure(cls, df: "pd.DataFrame", title: str) -> "Figure":
        """Stand-alone figure with this plotter's axes, drawn from `df`."""
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(1, cls.n_axes, figsize=cls.figsize)
        axes_list = list(axes) if cls.n_axes > 1 else [axes]
        cls.plot_data(axes_list, df, title)
        fig.tight_layout()
        return fig

    @classmethod
    def save_figure(cls, plots_dir: str, df: "pd.DataFrame", run_id: str, name: str) -> str:
        """Build, save, and close the figure (closing matters for long runs)."""
        import matplotlib.pyplot as plt

        fig = cls.figure(df, f"{name.upper()} -- run {run_id}")
        path = os.path.join(plots_dir, f"{name}.png")
        fig.savefig(path, dpi=150)
        plt.close(fig)
        return path

    @classmethod
    def figure_multi(cls, dfs_dict: dict[str, pd.DataFrame], title: str) -> "Figure":
        """Stand-alone figure with this plotter's axes, overlaying multiple datasets.

        `dfs_dict` maps run label -> DataFrame.
        """
        import matplotlib.pyplot as plt
        from potentiostat.plotting.plot_style import style_axes

        style_axes(plt)
        n_ax = getattr(cls, "n_axes_multi", cls.n_axes)
        fig_sz = getattr(cls, "figsize_multi", cls.figsize)
        fig, axes = plt.subplots(1, n_ax, figsize=fig_sz)
        axes_list = list(axes) if n_ax > 1 else [axes]
        cls.plot_multi_data(axes_list, dfs_dict, title)
        fig.tight_layout()
        return fig

    @classmethod
    def save_multi_figure(cls, plots_dir: str, dfs_dict: dict[str, pd.DataFrame], name: str, title: str | None = None) -> str:
        """Build, save, and close a figure overlaying multiple datasets."""
        import matplotlib.pyplot as plt

        title = title or f"{name.upper()} -- Comparison ({len(dfs_dict)} runs)"
        fig = cls.figure_multi(dfs_dict, title)
        path = os.path.join(plots_dir, f"combined_{name.lower()}.png")
        fig.savefig(path, dpi=200, bbox_inches="tight" if getattr(cls, "n_axes_multi", cls.n_axes) > 1 else None)
        plt.close(fig)
        return path

    @classmethod
    def plot_multi_data(cls, axes: list["Axes"], dfs_dict: dict[str, "pd.DataFrame"], title: str) -> None:
        """Overlay multiple datasets on the provided axes."""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def plot_data(cls, axes: "list[Axes]", df: "pd.DataFrame", title: str) -> "list[Line2D]":
        """Draw the initial curves into `axes`, set labels, and return the
        lines in the order `update_lines` expects them."""

    @classmethod
    @abstractmethod
    def update_lines(cls, lines: "list[Line2D]", data: np.ndarray) -> None:
        """Repaint `lines` from raw acq_data() and rescale their axes."""


class OCPPlotter(TechniquePlotter):
    @classmethod
    def plot_data(cls, axes, df, title="OCP"):
        ax = axes[0]
        (line,) = ax.plot(df["Time (s)"], df["OCP (V)"], color=BLUE, linewidth=1.5)
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("OCP (V)")
        ax.set_title(title)
        return [line]

    @classmethod
    def plot_multi_data(cls, axes, dfs_dict, title="OCP"):
        import matplotlib.pyplot as plt
        ax = axes[0]
        cmap = plt.get_cmap("tab10")
        for i, (label, df) in enumerate(dfs_dict.items()):
            col = cmap(i % 10)
            ax.plot(df["Time (s)"], df["OCP (V)"], label=label, color=col, linewidth=1.5)
        ax.set_xlabel("Time (s)", fontweight="bold")
        ax.set_ylabel("OCP (V)", fontweight="bold")
        ax.set_title(title, fontweight="bold", pad=12)
        ax.legend(frameon=True, facecolor="#ffffff", edgecolor="#c3c2b7")

    @classmethod
    def update_lines(cls, lines, data):
        lines[0].set_data(data["time"], data["vf"])
        lines[0].axes.relim()
        lines[0].axes.autoscale_view()


class LPRPlotter(TechniquePlotter):
    @classmethod
    def plot_data(cls, axes, df, title="LPR"):
        ax = axes[0]
        (line,) = ax.plot(df["Potential (V)"], df["Current (A)"], color=BLUE, linewidth=1.5)
        ax.set_xlabel("Potential (V)")
        ax.set_ylabel("Current (A)")
        ax.set_title(title)
        return [line]

    @classmethod
    def plot_multi_data(cls, axes, dfs_dict, title="LPR"):
        import matplotlib.pyplot as plt
        ax = axes[0]
        cmap = plt.get_cmap("tab10")
        for i, (label, df) in enumerate(dfs_dict.items()):
            col = cmap(i % 10)
            ax.plot(df["Potential (V)"], df["Current (A)"], label=label, color=col, linewidth=1.5)
        ax.set_xlabel("Potential (V)", fontweight="bold")
        ax.set_ylabel("Current (A)", fontweight="bold")
        ax.set_title(title, fontweight="bold", pad=12)
        ax.legend(frameon=True, facecolor="#ffffff", edgecolor="#c3c2b7")

    @classmethod
    def update_lines(cls, lines, data):
        lines[0].set_data(data["vf"], data["im"])
        lines[0].axes.relim()
        lines[0].axes.autoscale_view()


class CPPPlotter(TechniquePlotter):
    figsize = (7, 5)

    @classmethod
    def plot_data(cls, axes, df, title="CPP"):
        ax = axes[0]
        if "Leg" in df and df["Leg"].nunique() > 1:
            segment_col = "Leg"
        elif "table" in df and df["table"].nunique() > 1:
            segment_col = "table"
        elif "Cycle" in df:
            segment_col = "Cycle"
        else:
            segment_col = None

        if segment_col:
            colors = {seg: (BLUE if i == 0 else ORANGE) for i, seg in enumerate(df[segment_col].unique())}
            lines = []
            for seg, group in df.groupby(segment_col):
                logi = np.log10(group["Current_A"].abs().replace(0, float("nan")))
                (line,) = ax.plot(logi, group["Potential_V"], color=colors[seg], linewidth=1.5, label=f"{segment_col}={seg}")
                lines.append(line)
            ax.legend(frameon=False)
        else:
            logi = np.log10(df["Current_A"].abs().replace(0, float("nan")))
            lines = list(ax.plot(logi, df["Potential_V"], color=BLUE, linewidth=1.5))

        ax.set_xlabel("log|I| (A)")
        ax.set_ylabel("Potential (V)")
        ax.set_title(title)
        return lines

    @classmethod
    def plot_multi_data(cls, axes, dfs_dict, title="CPP"):
        import matplotlib.pyplot as plt
        ax = axes[0]
        cmap = plt.get_cmap("tab10")
        for i, (label, df) in enumerate(dfs_dict.items()):
            col = cmap(i % 10)
            pot_col = "Potential_V" if "Potential_V" in df else "Potential (V)"
            curr_col = "Current_A" if "Current_A" in df else "Current (A)"
            logi = np.log10(df[curr_col].abs().replace(0, float("nan")))
            ax.plot(logi, df[pot_col], label=label, color=col, linewidth=1.5)
        ax.set_xlabel("log|I| (A)", fontweight="bold")
        ax.set_ylabel("Potential (V)", fontweight="bold")
        ax.set_title(title, fontweight="bold", pad=12)
        ax.legend(frameon=True, facecolor="#ffffff", edgecolor="#c3c2b7")

    @classmethod
    def update_lines(cls, lines, data):
        im = np.where(data["im"] == 0, np.nan, np.abs(data["im"]))
        lines[0].set_data(np.log10(im), data["vf"])
        lines[0].axes.relim()
        lines[0].axes.autoscale_view()


class EISPlotter(TechniquePlotter):
    n_axes = 2
    n_axes_multi = 3
    figsize = (11, 4.5)
    figsize_multi = (15.5, 4.5)

    @classmethod
    def plot_data(cls, axes, df, title=None):
        """`axes` is [Nyquist axes, Bode axes]; the Bode panel gets a twin
        y-axis for phase."""
        ax_nyq, ax_mag = axes[0], axes[1]

        (nyquist,) = ax_nyq.plot(df["ZRe (Ohm)"], df["-ZIm (Ohm)"], "o-", color=BLUE, markersize=4, linewidth=1)
        ax_nyq.set_xlabel("Z' (ohm)")
        ax_nyq.set_ylabel("-Z'' (ohm)")
        ax_nyq.set_title("Nyquist")
        ax_nyq.set_aspect("equal", adjustable="datalim")

        (mag,) = ax_mag.loglog(df["Applied Frequency (Hz)"], df["Z (Ohm)"], "o-", color=BLUE, markersize=4, linewidth=1)
        ax_mag.set_xlabel("Frequency (Hz)")
        ax_mag.set_ylabel("|Z| (ohm)", color=BLUE)
        ax_mag.tick_params(axis="y", labelcolor=BLUE)
        ax_mag.set_title("Bode")

        ax_phz = ax_mag.twinx()
        (phase,) = ax_phz.semilogx(df["Applied Frequency (Hz)"], df["Phase (degree)"], "o-", color=ORANGE, markersize=4, linewidth=1)
        ax_phz.set_ylabel("Phase (deg)", color=ORANGE)
        ax_phz.tick_params(axis="y", labelcolor=ORANGE)
        ax_phz.grid(False)

        if title:
            ax_nyq.figure.suptitle(title)
        return [nyquist, mag, phase]

    @classmethod
    def plot_multi_data(cls, axes, dfs_dict, title="EIS"):
        import matplotlib.pyplot as plt

        if len(axes) >= 3:
            ax_nyq, ax_mag, ax_phz = axes[0], axes[1], axes[2]
            twin_phz = False
        else:
            ax_nyq, ax_mag = axes[0], axes[1]
            ax_phz = ax_mag.twinx()
            twin_phz = True

        cmap = plt.get_cmap("tab10")

        for i, (label, df) in enumerate(dfs_dict.items()):
            col = cmap(i % 10)
            ax_nyq.plot(df["ZRe (Ohm)"], df["-ZIm (Ohm)"], "o-", color=col, markersize=3, linewidth=1.2, label=label)
            ax_mag.loglog(df["Applied Frequency (Hz)"], df["Z (Ohm)"], "o-", color=col, markersize=3, linewidth=1.2, label=label)
            if twin_phz:
                ax_phz.semilogx(df["Applied Frequency (Hz)"], df["Phase (degree)"], "s--", color=col, markersize=3, linewidth=1.2, alpha=0.6)
            else:
                ax_phz.semilogx(df["Applied Frequency (Hz)"], df["Phase (degree)"], "o-", color=col, markersize=3, linewidth=1.2, label=label)

        ax_nyq.set_xlabel("Z' (Ohm)", fontweight="bold")
        ax_nyq.set_ylabel("-Z'' (Ohm)", fontweight="bold")
        ax_nyq.set_title("Nyquist Plot", fontweight="bold")
        ax_nyq.set_aspect("equal", adjustable="datalim")
        ax_nyq.legend(frameon=True, facecolor="#ffffff", edgecolor="#c3c2b7", fontsize="small")

        ax_mag.set_xlabel("Frequency (Hz)", fontweight="bold")
        ax_mag.set_ylabel("|Z| (Ohm)", fontweight="bold")
        ax_mag.set_title("Bode Magnitude (|Z|)", fontweight="bold")
        ax_mag.legend(frameon=True, facecolor="#ffffff", edgecolor="#c3c2b7", fontsize="small")

        ax_phz.set_xlabel("Frequency (Hz)", fontweight="bold")
        ax_phz.set_ylabel("Phase (deg)", fontweight="bold")
        ax_phz.set_title("Bode Phase Angle", fontweight="bold")
        if not twin_phz:
            ax_phz.legend(frameon=True, facecolor="#ffffff", edgecolor="#c3c2b7", fontsize="small")

        if title:
            ax_nyq.figure.suptitle(title, y=1.03, fontsize=12, fontweight="bold")

    @classmethod
    def update_lines(cls, lines, data):
        nyquist, mag, phase = lines[0], lines[1], lines[2]
        nyquist.set_data(data["zreal"], -data["zimag"])
        mag.set_data(data["zfreq"], data["zmod"])
        phase.set_data(data["zfreq"], data["zphz"])
        for line in (nyquist, mag, phase):
            line.axes.relim()
            line.axes.autoscale_view()


