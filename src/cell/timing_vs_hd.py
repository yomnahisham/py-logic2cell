"""Our generated cells against the installed HD cells, in timing (option 1 handout, Table 4 Timing; section 6).

    python -m src.cell.timing_vs_hd [ours:hd ...] [--out=<stem>]   e.g. dd2_gc1__nand2_1:nand2_1
                                     (default: the six of 4.1, written to results/timing_vs_hd.*)

Table 4 asks to characterize both cells with our own flow and compare, so the HD side is the installed
layout characterized by us (build/char/<hd>/..._timing.json, from char_validate or characterize hd); our side
is build/cells/<ours>/<ours>_timing.json (characterize ours, on the HD cell's grid). The shipped Liberty
value is shown beside them for reference. For each pair:
  - per table, the median and the largest difference of ours against HD over the whole grid;
  - section 6's point: delay and transition at the HD table entry nearest 100 ps and 10 fF;
  - every pin's input capacitance.
Pins are matched by name, so a pair needs the same pin names (true for the reference cells, which take
theirs from the installed SPICE netlist). Writes results/timing_vs_hd.csv (the point and the capacitances,
one row per value) and results/timing_vs_hd.txt (the summary).
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path

from src.cell.characterize import CAP_POINT, nearest
from src.cell.liberty_timing import read_cell
from src.paths import PREFIX

ROOT = Path(__file__).resolve().parents[2]
PAIRS = [(f"dd2_gc1__{c}", c) for c in ["inv_1", "nand2_1", "nor2_1", "nand3_1", "a21oi_1", "o21ai_1"]]


def load(ours: str, hd: str) -> tuple[dict, dict]:
    a = ROOT / "build/cells" / ours / f"{ours}_timing.json"
    b = ROOT / "build/char" / hd / f"{PREFIX}{hd}_timing.json"
    for p, how in ((a, f"python -m src.cell.characterize ours <request> --grid-from {hd}"),
                   (b, f"python -m src.cell.characterize hd {hd}")):
        if not p.exists():
            raise FileNotFoundError(f"{p} is missing: run {how}")
    return json.loads(a.read_text()), json.loads(b.read_text())


def compare(ours_name: str, hd_name: str) -> tuple[list[str], list[dict]]:
    ours, hd = load(ours_name, hd_name)
    lib = read_cell(hd_name)
    hd_arcs = {a["pin"]: a for a in hd["arcs"]}
    lib_arcs = {a.pin: a for a in lib.arcs if not a.when}
    lines, rows = [f"{ours_name} against {PREFIX}{hd_name}"], []
    for arc in ours["arcs"]:
        pin = arc["pin"]
        if pin not in hd_arcs:
            raise ValueError(f"{hd_name} has no arc for pin {pin}")
        theirs = hd_arcs[pin]
        if (arc["index_1"], arc["index_2"]) != (theirs["index_1"], theirs["index_2"]):
            raise ValueError(f"{pin}: the two runs used different grids")
        i, j = nearest(arc["index_1"], CAP_POINT[0]), nearest(arc["index_2"], CAP_POINT[1])
        if arc["sense"] != theirs["sense"]:
            lines.append(f"  {pin}: timing sense ours {arc['sense']}, HD {theirs['sense']}")
        for table, values in arc["tables"].items():
            diffs = [(v - h) / h * 100 for r_o, r_h in zip(values, theirs["tables"][table])
                     for v, h in zip(r_o, r_h) if v is not None and h is not None]
            v, h = values[i][j], theirs["tables"][table][i][j]
            lt = lib_arcs[pin].tables[table]
            shipped = lt["values"][nearest(lt["index_1"], arc["index_1"][i])][nearest(lt["index_2"], arc["index_2"][j])]
            worst = max(diffs, key=abs)
            lines.append(f"  {pin:3s} {table:16s} at {arc['index_1'][i]:.4g} ns / {arc['index_2'][j]:.4g} pF: "
                         f"ours {v:.4f}  HD {h:.4f} ns ({(v - h) / h * 100:+.1f}%)  [shipped {shipped:.4f}]   "
                         f"whole grid: median {statistics.median(diffs):+.1f}%, largest {worst:+.1f}%")
            rows.append(dict(cell=ours_name, hd=PREFIX + hd_name, pin=pin, value=table, slew_ns=arc["index_1"][i],
                             load_pf=arc["index_2"][j], ours=v, hd_our_flow=h, hd_shipped=shipped,
                             diff_pct=(v - h) / h * 100, grid_median_pct=statistics.median(diffs),
                             grid_largest_pct=worst))
    for pin, c in ours["pins"].items():
        v, h = c["capacitance"], hd["pins"][pin]["capacitance"]
        shipped = lib.capacitance[pin]["capacitance"]
        lines.append(f"  {pin:3s} capacitance: ours {v:.6f}  HD {h:.6f} pF ({(v - h) / h * 100:+.1f}%)  [shipped {shipped:.6f}]")
        rows.append(dict(cell=ours_name, hd=PREFIX + hd_name, pin=pin, value="capacitance", slew_ns="", load_pf="",
                         ours=v, hd_our_flow=h, hd_shipped=shipped, diff_pct=(v - h) / h * 100,
                         grid_median_pct="", grid_largest_pct=""))
    return lines, rows


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--out=")]
    stem = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--out=")), "timing_vs_hd")
    pairs = [tuple(a.split(":")) for a in args] or PAIRS
    report, rows = [], []
    for ours, hd in pairs:
        lines, r = compare(ours, hd)
        report += lines + [""]
        rows += r
    out = ROOT / "results"
    with (out / f"{stem}.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (out / f"{stem}.txt").write_text("\n".join(report))
    print("\n".join(report))
