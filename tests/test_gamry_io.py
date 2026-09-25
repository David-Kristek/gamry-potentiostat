"""gamry_io: reading multi-table .DTA files back into a DataFrame, patching a
header for POLRES, and writing a POLRES file."""

from __future__ import annotations

import pandas as pd

from potentiostat.parsing import gamry_io


def _render_table(tag, columns, units, rows, count=True):
    """Render one Gamry-style "<TAG>\\tTABLE[\\t<n>]" block, tabs and trailing
    tab included, exactly the layout read_dta_curve expects."""
    out = [f"{tag}\tTABLE" + (f"\t{len(rows)}" if count else "")]
    out.append("\t" + "\t".join(columns) + "\t")
    out.append("\t" + "\t".join(units) + "\t")
    for row in rows:
        out.append("\t" + "\t".join(row) + "\t")
    return out


def _write_dta(tmp_path, lines, name="sample.DTA"):
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="latin-1")
    return path


def test_read_dta_curve_parses_and_concatenates_tables(tmp_path):
    lines = ["EXPLAIN", "TAG\tExperiment", ""]
    lines += _render_table(
        "CURVE",
        ["Pt", "Time (s)", "Vf (V)", "Im (A)"],
        ["#", "s", "V", "A"],
        [["0", "0.0", "-0.1", "1.5e-6"], ["1", "1.0", "0.0", "2.5e-6"], ["2", "2.0", "0.1", "3.5e-6"]],
    )
    lines += [""]
    lines += _render_table(
        "CURVE2",
        ["Pt", "Time (s)", "Vf (V)", "Im (A)"],
        ["#", "s", "V", "A"],
        [["0", "0.0", "0.2", "4.5e-6"], ["1", "1.0", "0.1", "5.5e-6"]],
    )

    df = gamry_io.read_dta_curve(str(_write_dta(tmp_path, lines)))

    assert list(df.columns) == ["table", "Pt", "Time (s)", "Vf (V)", "Im (A)"]
    assert list(df["table"]) == ["CURVE", "CURVE", "CURVE", "CURVE2", "CURVE2"]
    assert list(df["Vf (V)"]) == [-0.1, 0.0, 0.1, 0.2, 0.1]
    # Values are coerced to numeric, not left as strings.
    assert df["Im (A)"].dtype.kind == "f"
    assert list(df["Pt"]) == [0.0, 1.0, 2.0, 0.0, 1.0]


def test_read_dta_curve_handles_comma_decimal_separator(tmp_path):
    lines = _render_table(
        "CURVE",
        ["Pt", "Vf (V)"],
        ["#", "V"],
        [["0", "1,5"], ["1", "2,5"]],
    )
    df = gamry_io.read_dta_curve(str(_write_dta(tmp_path, lines)))
    assert list(df["Vf (V)"]) == [1.5, 2.5]


def test_read_dta_curve_without_explicit_row_count(tmp_path):
    lines = _render_table("CURVE", ["Pt", "Vf (V)"], ["#", "V"], [["0", "0.1"], ["1", "0.2"]], count=False)
    lines += [""]
    lines += _render_table("CURVE2", ["Pt", "Vf (V)"], ["#", "V"], [["0", "0.3"]], count=False)

    df = gamry_io.read_dta_curve(str(_write_dta(tmp_path, lines)))

    assert list(df["table"]) == ["CURVE", "CURVE", "CURVE2"]
    assert list(df["Vf (V)"]) == [0.1, 0.2, 0.3]


def test_read_dta_curve_with_no_tables_returns_empty_frame(tmp_path):
    df = gamry_io.read_dta_curve(str(_write_dta(tmp_path, ["EXPLAIN", "TAG\tExperiment", ""])))
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_to_explain_header_patches_toolkitpy_placeholder_and_adds_notes():
    header = "TOOLKITPY\nTAG\tExperiment\nTime\n\nPSTAT\tPSTAT1\t0\n"

    out = gamry_io._to_explain_header(header)

    assert out.startswith("EXPLAIN\n")
    assert "TOOLKITPY" not in out
    assert "NOTES\tNOTES\t0\t&Notes...\n\nPSTAT\t" in out


class _Log:
    def error(self, err):  # pragma: no cover - only hit on write failure
        raise AssertionError(f"unexpected write failure: {err!r}")


class _FakeTkp:
    def __init__(self):
        self.log = _Log()

    def get_default_file_header(self, pstat, experiment_tag):
        return "TOOLKITPY\nTAG\tExperiment\nTime\n\nPSTAT\tPSTAT1\t0\n"


class _FakeCurve:
    def data_table(self):
        return "\tPt\tVf (V)\n\t#\tV\n\t0\t0.1\n"


def test_write_polarization_resistance_dta_file(tmp_path):
    path = tmp_path / "POLRES.dta"

    gamry_io.write_polarization_resistance_dta_file(
        _FakeTkp(),
        _FakeCurve(),
        None,
        str(path),
        v_init=-0.01,
        v_final=0.01,
        scan_rate_v_s=0.25,
        sample_time=1.0,
        area=0.57,
        density=7.87,
        equiv=27.92,
        beta_a=0.12,
        beta_c=0.12,
    )

    text = path.read_text()
    assert text.startswith("EXPLAIN\n")
    assert "NOTES\tNOTES\t0\t&Notes...\n\nPSTAT\t" in text
    assert "VINIT\tPOTEN\t-0.01\tT\tInitial E (V)\n" in text
    assert "VFINAL\tPOTEN\t0.01\tT\tFinal E (V)\n" in text
    assert "SCANRATE\tQUANT\t250.0\tScan Rate (mV/s)\n" in text  # 0.25 V/s -> 250 mV/s
    assert "SAMPLETIME\tQUANT\t1.0\tSample Period (s)\n" in text
    # The curve's own data table is appended verbatim.
    assert text.endswith("\tPt\tVf (V)\n\t#\tV\n\t0\t0.1\n")
