"""
gamry_io.py
-----------
CSV export helpers, plus DTA writing for POLRES (ToolkitPy has no writer for
it at all; _to_explain_header patches its header to what Echem Analyst 2's
script analyses require, same as before). OCP/EIS/CYCPOL DTA writing now goes
straight through ToolkitPy's own tkp.print_default_dta_file() /
tkp.print_cyclic_polarization_dta_file().

read_dta_curve() is the read-path counterpart, used by notebooks/plot_runs.ipynb
and workflow/origin_export.py to get every column (including Pt/T/Cycle, which
the CSV exports above drop) straight back out of a .DTA file.
"""

from __future__ import annotations

import pandas as pd


# --- DTA writing (POLRES: ToolkitPy has no native writer, Echem Analyst 2 needs a patched header) ---


def _to_explain_header(header_str: str) -> str:
    """Patch a tkp.get_default_file_header() string to what Echem Analyst 2
    requires to accept the file: "EXPLAIN" as the literal first line (not
    ToolkitPy's own "TOOLKITPY" placeholder) and a NOTES block before the
    PSTAT section. Relies on toolkitcommon.py's exact header layout --
    "...Time\\n\\nPSTAT\\t..." -- to anchor the insertion.
    """
    header_str = header_str.replace("TOOLKITPY\n", "EXPLAIN\n", 1)
    return header_str.replace("\n\nPSTAT\t", "\nNOTES\tNOTES\t0\t&Notes...\n\nPSTAT\t", 1)


def write_polarization_resistance_dta_file(
    tkp,
    curve,
    pstat,
    fname: str,
    v_init: float,
    v_final: float,
    scan_rate_v_s: float,
    sample_time: float,
    area: float,
    density: float,
    equiv: float,
    beta_a: float,
    beta_c: float,
    experiment_tag: str = "POLRES",
) -> None:
    file_header = _to_explain_header(tkp.get_default_file_header(pstat, experiment_tag))
    file_header += f"VINIT\tPOTEN\t{v_init}\tT\tInitial E (V)\n"
    file_header += f"VFINAL\tPOTEN\t{v_final}\tT\tFinal E (V)\n"
    # Header matches Gamry's own convention (and sequence_parser.py, which reads
    # SCANRATE back as mV/s): the config value is V/s, so convert here.
    file_header += f"SCANRATE\tQUANT\t{scan_rate_v_s * 1000.0}\tScan Rate (mV/s)\n"
    file_header += f"SAMPLETIME\tQUANT\t{sample_time}\tSample Period (s)\n"
    file_header += f"AREA\tQUANT\t{area}\tSample Area (cm^2)\n"
    file_header += f"DENSITY\tQUANT\t{density}\tDensity (g/cm^3)\n"
    file_header += f"EQUIV\tQUANT\t{equiv}\tEquiv. Wt\n"
    file_header += f"BETAA\tQUANT\t{beta_a}\tBeta An.(V/Dec)\n"
    file_header += f"BETAC\tQUANT\t{beta_c}\tBeta Cat.(V/Dec)\n"

    data_table = curve.data_table()

    try:
        with open(fname, "w") as file:
            file.write(file_header)
            file.write(data_table)
    except Exception as err:
        tkp.log.error(err)


# --- DTA reading (for plotting / Origin export past runs) ---


def read_dta_curve(dta_path: str) -> pd.DataFrame:
    """Pull every data table out of a Gamry-style .DTA file into one DataFrame.

    Gamry/ToolkitPy .DTA files are plain text: metadata lines, then one or
    more "<TAG>\tTABLE[\t<n_rows>]" blocks (e.g. CURVE/ZCURVE for most
    techniques, but cyclic polarization splits forward/reverse into separate
    CURVE1/CURVE2 tables), each followed by a column-name row, a units row,
    and data rows (prefixed with a leading blank field from the file's leading tab).

    Every table found is parsed and concatenated, tagged with which table
    ("CURVE", "CURVE1", "CURVE2", "ZCURVE", ...) each row came from.
    Handles comma decimal separators and missing explicit row counts.
    """
    with open(dta_path, "r", encoding="latin-1") as f:
        lines = f.readlines()

    tables = []
    i = 0
    n_lines = len(lines)
    while i < n_lines:
        parts = lines[i].rstrip("\r\n").split("\t")
        if len(parts) >= 2 and parts[1].strip() == "TABLE":
            tag = parts[0].strip()
            n_rows = None
            if len(parts) >= 3:
                try:
                    n_rows = int(float(parts[2]))
                except ValueError:
                    n_rows = None

            columns = [c.strip() for c in lines[i + 1].rstrip("\r\n").split("\t")][1:]
            data_start = i + 3  # skip column-name row and units row

            rows = []
            r = 0
            while data_start + r < n_lines:
                if n_rows is not None and r >= n_rows:
                    break
                line_content = lines[data_start + r].rstrip("\r\n")
                if not line_content or not line_content.startswith("\t"):
                    break
                cells = [cell.strip().replace(",", ".") for cell in line_content.split("\t")[1:]]
                rows.append(cells[: len(columns)])
                r += 1

            df = pd.DataFrame(rows, columns=columns)
            df = df.loc[:, [c != "" for c in df.columns]]  # drop trailing-tab ghost column
            df = df.apply(pd.to_numeric, errors="coerce")
            df.insert(0, "table", tag)
            tables.append(df)
            i = data_start + (n_rows if n_rows is not None else r)
        else:
            i += 1

    if not tables:
        return pd.DataFrame()
    return pd.concat(tables, ignore_index=True)
