"""
save_plots.py
-------------
Post-run PNG writers, via each technique's plotter (Technique.plotter):
`save_plots` writes one figure per technique that produced data in a run;
`save_combined_plots` overlays the same technique across several runs.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

import pandas as pd

from potentiostat.plotting.plot_style import style_axes
from potentiostat.core.techniques.technique import SequenceResults, Technique


def save_plots(run_id: str, dfs: SequenceResults, plots_dir: str) -> list[str]:
    """Save whichever of OCP/EIS/LPR/CPP have data in `dfs` as PNGs in `plots_dir`.

    `dfs` is {key: result dict or None}; `key` is a technique name ("eis") or,
    for a repeated technique, an occurrence key ("eis_2", see
    workflow.technique_keys). Returns the list of PNG paths written.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(plots_dir, exist_ok=True)
    style_axes(plt)

    saved = []
    for key, result in dfs.items():
        csv_path = result.csv_path if result is not None else None
        if csv_path is None:
            continue
        try:
            plotter = Technique.from_key(key).plotter
        except KeyError:
            continue
        if plotter is None:
            continue
        df = pd.read_csv(csv_path)
        saved.append(plotter.save_figure(plots_dir, df, run_id, key))

    return saved


def save_combined_plots(runs: Mapping[str, SequenceResults], plots_dir: str, title_suffix: str = "") -> list[str]:
    """Overlay the same technique across several runs, one `combined_<key>.png` each.

    `runs` is {run label: SequenceResults} (the label becomes the legend
    entry). Results are grouped by technique key, so "eis" is only compared
    with "eis" and a repeated "eis_2" gets its own figure. A technique with
    fewer than two runs is skipped (nothing to compare). Returns the PNG paths
    written.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(plots_dir, exist_ok=True)
    style_axes(plt)

    by_key: dict[str, dict[str, str]] = {}
    for label, results in runs.items():
        for key, result in results.items():
            if result is not None and result.csv_path:
                by_key.setdefault(key, {})[label] = result.csv_path

    saved = []
    for key, csv_paths in by_key.items():
        if len(csv_paths) < 2:
            continue
        try:
            plotter = Technique.from_key(key).plotter
        except KeyError:
            continue
        if plotter is None:
            continue
        dfs = {label: pd.read_csv(path) for label, path in csv_paths.items()}
        title = f"{key.upper()} -- {len(dfs)} runs{f' ({title_suffix})' if title_suffix else ''}"
        saved.append(plotter.save_multi_figure(plots_dir, dfs, name=key, title=title))

    return saved
