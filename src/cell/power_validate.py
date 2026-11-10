"""Validate the characterizer's power against the shipped HD Liberty, as Table 5 validates its timing:
the installed reference cells, extracted and characterized with our flow, against their own power tables.

    python -m src.cell.power_validate [cells ...] [--grid N]     -> results/power_validation.txt, _entries.csv

Compared, entry by entry on the HD cell's own indexes (a --grid subset of them):
  - leakage_power in every input state (nW; HD gives one group per `when` state);
  - internal_power of each output arc, rise_power and fall_power (pJ per transition, HD's convention: the
    energy drawn from VPWR less C V^2 / 2 of the load; characterize.measure).
The input pins' own internal_power (energy when an input toggles without switching the output) is not
measured. The runs are tagged _power so the full-grid timing of char_validate is not overwritten.
"""

from __future__ import annotations

import argparse
import csv
import statistics
from pathlib import Path

from src.cell.characterize import characterize_hd, nearest
from src.cell.liberty_timing import cell_text, numbers, parse
from src.paths import LIBERTY_TT, PREFIX

ROOT = Path(__file__).resolve().parents[2]
CELLS = ["inv_1", "nand2_1", "nor2_1", "nand3_1", "a21oi_1", "o21ai_1"]


def shipped(short: str) -> tuple[dict, dict]:
    """HD's leakage {when: nW} and internal power {(pin, kind): (index_1, index_2, values)} of one cell."""
    cell = parse(cell_text(LIBERTY_TT, PREFIX + short)).all("cell")[0]
    leak = {g.attrs["when"].replace(" ", ""): float(g.attrs["value"]) for g in cell.all("leakage_power")}
    power = {}
    for pin in cell.all("pin"):
        if pin.attrs.get("direction") != "output":
            continue
        for ip in pin.all("internal_power"):
            for g in ip.groups:
                if g.kind in ("rise_power", "fall_power"):
                    power[(ip.attrs["related_pin"], g.kind)] = (numbers(g.attrs["index_1"][0]),
                                                                numbers(g.attrs["index_2"][0]),
                                                                [numbers(r) for r in g.attrs["values"]])
    return leak, power


def same_state(a: str, b: str) -> bool:
    """Two `when` conditions over the same literals, in any order."""
    return sorted(a.split("&")) == sorted(b.split("&"))


def main(cells: list[str], grid: int | None):
    rows, lines = [], []
    for short in cells:
        ours = characterize_hd(short, grid, tag="_power")
        leak, power = shipped(short)
        for state, value in ours["leakage_nw"].items():
            hd = next((v for w, v in leak.items() if same_state(w, state)), None)
            if hd:
                rows.append(dict(cell=short, kind="leakage", pin="", state=state, slew_ns="", load_pf="",
                                 ours=round(value, 6), hd=hd, err_pct=round((value - hd) / hd * 100, 2)))
        for arc in ours["arcs"]:
            for kind, table in arc["power"].items():
                if (arc["pin"], kind) not in power:
                    continue
                i1, i2, hd_vals = power[(arc["pin"], kind)]
                for i, s in enumerate(arc["index_1"]):
                    for j, c in enumerate(arc["index_2"]):
                        v, h = table[i][j], hd_vals[nearest(i1, s)][nearest(i2, c)]
                        if v is None:
                            continue
                        # the error on the energy the cell itself spends: |h| can be near zero where the
                        # internal energy crosses from positive to negative, so relative to C V^2 / 2 + |h|
                        scale = abs(h) + 0.5 * c * ours["setup"]["nom_voltage"] ** 2
                        rows.append(dict(cell=short, kind=kind, pin=arc["pin"], state="", slew_ns=s, load_pf=c,
                                         ours=round(v, 6), hd=h, err_pct=round((v - h) / scale * 100, 2)))
    out = ROOT / "results"
    with (out / "power_validation_entries.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    lines.append(f"Power against the shipped HD Liberty (sky130_fd_sc_hd__tt_025C_1v80.lib), cells {', '.join(cells)}")
    lines.append("internal energy error relative to C V^2 / 2 + |HD value| (see the module docstring)")
    for kind in ("leakage", "rise_power", "fall_power"):
        errs = [abs(r["err_pct"]) for r in rows if r["kind"] == kind]
        if errs:
            worst = max((r for r in rows if r["kind"] == kind), key=lambda r: abs(r["err_pct"]))
            lines.append(f"{kind:11s} {len(errs):4d} entries  median |error| {statistics.median(errs):6.2f}%  "
                         f"largest {worst['err_pct']:+.1f}% at {worst['cell']} {worst['pin']} {worst['state']} "
                         f"{worst['slew_ns']} {worst['load_pf']}")
    for short in cells:
        errs = [abs(r["err_pct"]) for r in rows if r["cell"] == short and r["kind"] != "leakage"]
        leaks = [abs(r["err_pct"]) for r in rows if r["cell"] == short and r["kind"] == "leakage"]
        lines.append(f"  {short:8s} internal median {statistics.median(errs) if errs else float('nan'):6.2f}%   "
                     f"leakage median {statistics.median(leaks) if leaks else float('nan'):6.2f}%")
    (out / "power_validation.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cells", nargs="*", default=CELLS)
    ap.add_argument("--grid", type=int, default=3)
    args = ap.parse_args()
    main(args.cells, args.grid)
