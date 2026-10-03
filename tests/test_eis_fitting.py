from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from potentiostat.utils.eis_fitting import fit_eis, fit_eis_csv, read_eis_csv


def _randles_impedance(freq_hz, rs, rct, cdl):
    omega = 2.0 * np.pi * np.asarray(freq_hz, dtype=float)
    y_parallel = (1.0 / rct) + 1j * omega * cdl
    return rs + 1.0 / y_parallel


def _randles_cpe_impedance(freq_hz, rs, rct, q, n):
    omega = 2.0 * np.pi * np.asarray(freq_hz, dtype=float)
    y_parallel = (1.0 / rct) + q * (1j * omega) ** n
    return rs + 1.0 / y_parallel


def _write_eis_csv(path, freq_hz, z):
    df = pd.DataFrame(
        {
            "Applied Frequency (Hz)": freq_hz,
            "Z (Ohm)": np.abs(z),
            "ZRe (Ohm)": z.real,
            "-ZIm (Ohm)": -z.imag,
            "Phase (degree)": np.rad2deg(np.angle(z)),
        }
    )
    df.to_csv(path, index=False)


def test_fit_randles_parameter_recovery():
    freq = np.logspace(5, -1, 61)
    z = _randles_impedance(freq, rs=4.5, rct=120.0, cdl=2.0e-5)

    out = fit_eis(freq, z, circuit="randles", weighting="modulus")

    assert out.circuit == "randles"
    assert out.parameters["Rs"] == pytest.approx(4.5, rel=0.03)
    assert out.parameters["Rct"] == pytest.approx(120.0, rel=0.05)
    assert out.parameters["Cdl"] == pytest.approx(2.0e-5, rel=0.08)
    assert out.rmse < 1e-6


def test_fit_randles_cpe_parameter_recovery_unweighted():
    freq = np.logspace(5, -1, 61)
    z = _randles_cpe_impedance(freq, rs=3.0, rct=85.0, q=3.1e-5, n=0.82)

    out = fit_eis(freq, z, circuit="randles-cpe", weighting="unweighted")

    assert out.circuit == "randles-cpe"
    assert out.parameters["Rs"] == pytest.approx(3.0, rel=0.05)
    assert out.parameters["Rct"] == pytest.approx(85.0, rel=0.08)
    assert out.parameters["Q"] == pytest.approx(3.1e-5, rel=0.12)
    assert out.parameters["n"] == pytest.approx(0.82, rel=0.04)


def test_fit_eis_csv_converts_neg_zim_sign(tmp_path):
    csv_path = tmp_path / "eis.csv"
    freq = np.array([1000.0, 100.0])
    z = np.array([10.0 - 2.0j, 12.0 - 4.0j])
    _write_eis_csv(csv_path, freq, z)

    parsed_freq, parsed_z = read_eis_csv(str(csv_path))

    assert np.allclose(parsed_freq, freq)
    assert np.allclose(parsed_z, z)


def test_fit_eis_csv_to_json_export(tmp_path):
    csv_path = tmp_path / "eis.csv"
    json_path = tmp_path / "fit.json"

    freq = np.logspace(4, -1, 41)
    z = _randles_impedance(freq, rs=2.0, rct=40.0, cdl=5e-5)
    _write_eis_csv(csv_path, freq, z)

    out = fit_eis_csv(str(csv_path), circuit="randles")
    out.to_json(str(json_path))

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["circuit"] == "randles"
    assert set(payload["parameters"].keys()) == {"Rs", "Rct", "Cdl"}
    assert len(payload["frequency_hz"]) == len(freq)


def test_fit_eis_invalid_circuit_and_weighting():
    freq = np.array([100.0, 10.0])
    z = np.array([5.0 - 1.0j, 6.0 - 2.0j])

    with pytest.raises(ValueError, match="Unsupported circuit"):
        fit_eis(freq, z, circuit="warburg")

    with pytest.raises(ValueError, match="Unsupported weighting"):
        fit_eis(freq, z, weighting="magic")


def test_read_eis_csv_rejects_nonpositive_frequency_and_malformed_data(tmp_path):
    bad_freq = tmp_path / "bad_freq.csv"
    pd.DataFrame(
        {
            "Applied Frequency (Hz)": [1000.0, 0.0],
            "Z (Ohm)": [10.0, 11.0],
            "ZRe (Ohm)": [10.0, 11.0],
            "-ZIm (Ohm)": [1.0, 1.2],
            "Phase (degree)": [-5.0, -6.0],
        }
    ).to_csv(bad_freq, index=False)

    with pytest.raises(ValueError, match="positive"):
        read_eis_csv(str(bad_freq))

    missing_col = tmp_path / "missing_col.csv"
    pd.DataFrame(
        {
            "Applied Frequency (Hz)": [1000.0],
            "ZRe (Ohm)": [10.0],
            "-ZIm (Ohm)": [1.0],
            "Phase (degree)": [-5.0],
        }
    ).to_csv(missing_col, index=False)

    with pytest.raises(ValueError, match="Missing required EIS CSV columns"):
        read_eis_csv(str(missing_col))
