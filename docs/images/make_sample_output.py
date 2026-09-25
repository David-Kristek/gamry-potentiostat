"""Generate docs/images/sample-output.png for the README.

Synthetic data only -- no hardware involved. Run with any interpreter:

    python docs/images/make_sample_output.py
"""

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from potentiostat.plotting.plot_style import style_axes
from potentiostat.plotting.technique_plots import CPPPlotter, EISPlotter, LPRPlotter, OCPPlotter

OUT = os.path.join(os.path.dirname(__file__), "sample-output.png")
rng = np.random.default_rng(7)

# OCP: settle then slowly drift, with only light measurement noise.
t = np.linspace(0.0, 300.0, 181)
ocp = -0.245 + 0.012 * np.exp(-t / 45.0) + 0.00018 * t + rng.normal(0.0, 0.00015, t.size)
ocp_df = pd.DataFrame({"Time (s)": t, "OCP (V)": ocp})

# EIS: Randles cell (Rs + Rct || Cdl).
freq = np.logspace(5, -1, 61)
w = 2.0 * np.pi * freq
z = 12.0 + 220.0 / (1.0 + 1j * w * 220.0 * 8e-5)
eis_df = pd.DataFrame(
    {
        "Applied Frequency (Hz)": freq,
        "Z (Ohm)": np.abs(z),
        "ZRe (Ohm)": z.real,
        "-ZIm (Ohm)": -z.imag,
        "Phase (degree)": np.degrees(np.angle(z)),
    }
)

# LPR: narrow linear ramp.
v = np.linspace(-0.015, 0.015, 121)
lpr_df = pd.DataFrame({"Potential (V)": v, "Current (A)": v / 50.0 + rng.normal(0.0, 2e-6, v.size)})

# CPP: passive region, breakdown on the anodic leg, then hysteresis on the
# reverse leg (repassivation at a lower potential) -- the usual cyclic
# polarization loop when plotted as log|I| vs potential.
vf_fwd = np.linspace(-0.25, 1.5, 140)
vf_rev = np.linspace(1.5, 0.0, 110)
i_lo, i_pit = 1e-7, 1e-2


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


# Forward breaks down at ~1.05 V; the reverse repassivates at a lower ~0.6 V,
# giving the characteristic hysteresis loop without a flat current plateau.
im_fwd = i_lo + i_pit * _sigmoid((vf_fwd - 1.05) / 0.10)
im_rev = i_lo + i_pit * _sigmoid((vf_rev - 0.60) / 0.10)
cpp_df = pd.DataFrame(
    {
        "Potential_V": np.concatenate([vf_fwd, vf_rev]),
        "Current_A": np.concatenate([im_fwd, im_rev]),
        "Leg": ["CURVE1"] * vf_fwd.size + ["CURVE2"] * vf_rev.size,
    }
)

style_axes(plt, font_size=9)
fig = plt.figure(figsize=(15, 8))
gs = fig.add_gridspec(2, 3, hspace=0.45, wspace=0.3)
OCPPlotter.plot_data([fig.add_subplot(gs[0, 0])], ocp_df, "OCP")
LPRPlotter.plot_data([fig.add_subplot(gs[0, 1])], lpr_df, "LPR")
CPPPlotter.plot_data([fig.add_subplot(gs[0, 2])], cpp_df, "CPP")
EISPlotter.plot_data([fig.add_subplot(gs[1, 0]), fig.add_subplot(gs[1, 1:])], eis_df, "EIS")
fig.suptitle("potentiostat -- example output (synthetic data)", fontsize=13)
fig.savefig(OUT, dpi=150, bbox_inches="tight")
print("wrote", OUT)
