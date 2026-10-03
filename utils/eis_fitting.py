from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, Iterable, Tuple

import numpy as np
import pandas as pd


_REQUIRED_COLUMNS = (
    "Applied Frequency (Hz)",
    "Z (Ohm)",
    "ZRe (Ohm)",
    "-ZIm (Ohm)",
    "Phase (degree)",
)


@dataclass
class EISFitResult:
    circuit: str
    weighting: str
    parameters: Dict[str, float]
    rmse: float
    diagnostics: Dict[str, float]
    frequency_hz: np.ndarray
    z_measured: np.ndarray
    z_fitted: np.ndarray

    def to_dict(self) -> dict:
        return {
            "circuit": self.circuit,
            "weighting": self.weighting,
            "parameters": dict(self.parameters),
            "rmse": float(self.rmse),
            "diagnostics": dict(self.diagnostics),
            "frequency_hz": self.frequency_hz.tolist(),
            "z_measured_re": self.z_measured.real.tolist(),
            "z_measured_im": self.z_measured.imag.tolist(),
            "z_fitted_re": self.z_fitted.real.tolist(),
            "z_fitted_im": self.z_fitted.imag.tolist(),
        }

    def to_json(self, path: str | None = None, indent: int = 2) -> str:
        text = json.dumps(self.to_dict(), indent=indent)
        if path is not None:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        return text


def read_eis_csv(csv_path: str) -> Tuple[np.ndarray, np.ndarray]:
    df = pd.read_csv(csv_path)
    missing = [col for col in _REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError("Missing required EIS CSV columns: {0}".format(", ".join(missing)))

    freq = _to_numeric(df["Applied Frequency (Hz)"], "Applied Frequency (Hz)")
    z_re = _to_numeric(df["ZRe (Ohm)"], "ZRe (Ohm)")
    neg_z_im = _to_numeric(df["-ZIm (Ohm)"], "-ZIm (Ohm)")

    if np.any(freq <= 0):
        raise ValueError("All frequencies must be positive")

    z = z_re - 1j * neg_z_im
    return freq, z


def fit_eis_csv(csv_path: str, circuit: str = "randles", weighting: str = "modulus") -> EISFitResult:
    frequency_hz, z_measured = read_eis_csv(csv_path)
    return fit_eis(frequency_hz, z_measured, circuit=circuit, weighting=weighting)


def fit_eis(
    frequency_hz: Iterable[float],
    z_measured: Iterable[complex],
    circuit: str = "randles",
    weighting: str = "modulus",
) -> EISFitResult:
    frequency_hz = np.asarray(frequency_hz, dtype=float)
    z_measured = np.asarray(z_measured, dtype=complex)

    if frequency_hz.ndim != 1 or z_measured.ndim != 1 or len(frequency_hz) != len(z_measured):
        raise ValueError("frequency_hz and z_measured must be one-dimensional arrays with equal length")
    if len(frequency_hz) == 0:
        raise ValueError("No EIS points were provided")
    if not np.all(np.isfinite(frequency_hz)):
        raise ValueError("frequency_hz contains non-finite values")
    if np.any(frequency_hz <= 0):
        raise ValueError("All frequencies must be positive")
    if not np.all(np.isfinite(z_measured.real)) or not np.all(np.isfinite(z_measured.imag)):
        raise ValueError("z_measured contains non-finite values")

    circuit_key = circuit.lower().strip()
    weighting_key = weighting.lower().strip()

    if circuit_key not in ("randles", "randles-cpe", "randles_cpe"):
        raise ValueError("Unsupported circuit: {0}".format(circuit))
    if weighting_key not in ("modulus", "none", "unweighted"):
        raise ValueError("Unsupported weighting: {0}".format(weighting))

    if weighting_key == "none":
        weighting_key = "unweighted"

    omega = 2.0 * np.pi * frequency_hz

    x0, lower, upper, names = _initial_guess_and_bounds(circuit_key, frequency_hz, z_measured)

    measured_mod = np.abs(z_measured)
    if weighting_key == "modulus":
        weights = 1.0 / np.maximum(measured_mod, 1e-18)
    else:
        weights = np.ones_like(measured_mod)

    try:
        from scipy.optimize import least_squares
    except ImportError as exc:  # pragma: no cover
        raise ImportError("SciPy is required for EIS fitting. Install scipy>=1.7.") from exc

    def _residuals(params: np.ndarray) -> np.ndarray:
        z_fit = _model_impedance(circuit_key, omega, params)
        residual_re = (z_fit.real - z_measured.real) * weights
        residual_im = (z_fit.imag - z_measured.imag) * weights
        return np.concatenate([residual_re, residual_im])

    out = least_squares(_residuals, x0=x0, bounds=(lower, upper), method="trf")

    params = {name: float(value) for name, value in zip(names, out.x)}
    z_fitted = _model_impedance(circuit_key, omega, out.x)

    residual_re = z_fitted.real - z_measured.real
    residual_im = z_fitted.imag - z_measured.imag
    stacked_residuals = np.concatenate([residual_re, residual_im])

    rmse = float(np.sqrt(np.mean(stacked_residuals**2)))
    diagnostics = {
        "cost": float(out.cost),
        "nfev": float(out.nfev),
        "max_abs_residual": float(np.max(np.abs(stacked_residuals))),
    }

    return EISFitResult(
        circuit="randles-cpe" if circuit_key in ("randles-cpe", "randles_cpe") else "randles",
        weighting=weighting_key,
        parameters=params,
        rmse=rmse,
        diagnostics=diagnostics,
        frequency_hz=frequency_hz,
        z_measured=z_measured,
        z_fitted=z_fitted,
    )


def plot_eis_fit(result: EISFitResult, output_path: str | None = None):
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    ax_nyq, ax_mag = axes[0], axes[1]

    ax_nyq.plot(result.z_measured.real, -result.z_measured.imag, "o", markersize=4, label="Measured")
    ax_nyq.plot(result.z_fitted.real, -result.z_fitted.imag, "-", linewidth=1.2, label="Fitted")
    ax_nyq.set_xlabel("Z' (Ohm)")
    ax_nyq.set_ylabel("-Z'' (Ohm)")
    ax_nyq.set_title("Nyquist")
    ax_nyq.set_aspect("equal", adjustable="datalim")
    ax_nyq.legend(frameon=False)

    ax_mag.loglog(result.frequency_hz, np.abs(result.z_measured), "o", markersize=4, label="Measured |Z|")
    ax_mag.loglog(result.frequency_hz, np.abs(result.z_fitted), "-", linewidth=1.2, label="Fitted |Z|")
    ax_mag.set_xlabel("Frequency (Hz)")
    ax_mag.set_ylabel("|Z| (Ohm)")
    ax_mag.set_title("Bode magnitude")
    ax_mag.legend(frameon=False)

    fig.tight_layout()

    if output_path is not None:
        fig.savefig(output_path, dpi=150)

    return fig


def _initial_guess_and_bounds(
    circuit: str,
    frequency_hz: np.ndarray,
    z_measured: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Tuple[str, ...]]:
    rs0 = float(max(np.min(z_measured.real), 0.0))
    rct0 = float(max(np.max(z_measured.real) - rs0, 1e-6))

    idx = int(np.argmin(z_measured.imag))
    f_peak = float(frequency_hz[idx]) if frequency_hz[idx] > 0 else float(np.median(frequency_hz))
    cdl0 = float(np.clip(1.0 / (2.0 * np.pi * f_peak * max(rct0, 1e-12)), 1e-12, 1e3))

    if circuit == "randles":
        x0 = np.array([rs0, rct0, cdl0], dtype=float)
        lower = np.array([0.0, 0.0, 1e-30], dtype=float)
        upper = np.array([np.inf, np.inf, np.inf], dtype=float)
        names = ("Rs", "Rct", "Cdl")
    else:
        x0 = np.array([rs0, rct0, cdl0, 0.9], dtype=float)
        lower = np.array([0.0, 0.0, 1e-30, 0.0], dtype=float)
        upper = np.array([np.inf, np.inf, np.inf, 1.0], dtype=float)
        names = ("Rs", "Rct", "Q", "n")

    return x0, lower, upper, names


def _model_impedance(circuit: str, omega: np.ndarray, params: np.ndarray) -> np.ndarray:
    if circuit == "randles":
        rs, rct, cdl = params
        y_parallel = (1.0 / rct) + 1j * omega * cdl
        return rs + 1.0 / y_parallel

    rs, rct, q, n = params
    y_parallel = (1.0 / rct) + q * (1j * omega) ** n
    return rs + 1.0 / y_parallel


def _to_numeric(series: pd.Series, column_name: str) -> np.ndarray:
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    if np.any(~np.isfinite(values)):
        raise ValueError("Column '{0}' contains non-numeric or missing values".format(column_name))
    return values
