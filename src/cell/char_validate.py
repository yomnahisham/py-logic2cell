"""Validate the characterizer against the shipped HD Liberty (option 1 handout, section 5.1, Table 5).

    python -m src.cell.char_validate [cells ...] [--grid N] [--full-ramp] [--image IMAGE] [--tag T] [--no-run]

Characterizes the installed reference cells (default: the six of section 4.1) and compares every table
entry of every arc, and every input capacitance, with sky130_fd_sc_hd__tt_025C_1v80.lib:
  - delay and transition: the median of |error| over all entries of all cells must be 5% or less; the
    median per cell and the largest error, with where it occurs, are reported too;
  - input capacitance: every pin within 10% (capacitance, the mean of rise and fall, from the charge in
    the pin's slew window; the whole-run value is shown beside it for the report, not checked);
  - setup: the thresholds, voltage and temperature the runs used, which must equal the library's.
Writes results/char_validation<tag>.txt (summary), _entries.csv (every entry) and _caps.csv.
Exit status 0 if every requirement is met. With --full-ramp (the broken case) it must exit 1.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

from src.cell.characterize import characterize_hd
from src.cell.liberty_timing import read_cell, read_setup
from src.cell.tools import IMAGE
from src.paths import LIBERTY_TT, PREFIX

ROOT = Path(__file__).resolve().parents[2]
CELLS = ["inv_1", "nand2_1", "nor2_1", "nand3_1", "a21oi_1", "o21ai_1"]   # section 4.1
MEDIAN_LIMIT = 5.0     # %, Table 5
CAP_LIMIT = 10.0       # %, Table 5


def at(index: list[float], x: float) -> int:
    """Position of x in a table index; the indexes of one arc's tables differ only in rounding."""
    k = min(range(len(index)), key=lambda n: abs(index[n] - x))
    if abs(index[k] - x) > 1e-4 * max(abs(x), 1e-9):
        raise ValueError(f"no index value {x} in {index}")
    return k


def compare(short: str, ours: dict) -> tuple[list[dict], list[dict]]:
    hd = read_cell(short)
    entries, caps = [], []
    for arc in ours["arcs"]:
        theirs = [a for a in hd.arcs if a.pin == arc["pin"] and not a.when] or [a for a in hd.arcs if a.pin == arc["pin"]]
        if not theirs:
            raise ValueError(f"{hd.name}: no HD arc for pin {arc['pin']}")
        if theirs[0].sense != arc["sense"]:
            entries.append(dict(cell=short, pin=arc["pin"], table="timing_sense", slew_ns="", load_pf="",
                                ours=arc["sense"], hd=theirs[0].sense, error_pct=""))
        for name, values in arc["tables"].items():
            t = theirs[0].tables[name]
            for i, slew in enumerate(arc["index_1"]):
                for j, load in enumerate(arc["index_2"]):
                    ref = t["values"][at(t["index_1"], slew)][at(t["index_2"], load)]
                    v = values[i][j]
                    err = None if v is None else (v - ref) / ref * 100
                    entries.append(dict(cell=short, pin=arc["pin"], table=name, slew_ns=slew, load_pf=load,
                                        ours=v, hd=ref, error_pct=err))
    for pin, c in ours["pins"].items():
        for key in ("capacitance", "rise_capacitance", "fall_capacitance", "capacitance_full"):
            ref = hd.capacitance[pin].get(key.replace("_full", ""))     # the whole-run value, for the report only
            v = c.get(key)
            caps.append(dict(cell=short, pin=pin, kind=key, ours=v, hd=ref,
                             error_pct=None if v is None or ref is None else (v - ref) / ref * 100))
    return entries, caps


def summary(entries: list[dict], caps: list[dict], runs: dict, tag: str) -> tuple[list[str], bool]:
    lines, ok = [], True
    setup = read_setup()
    lines.append(f"Characterizer validation{tag}: {', '.join(runs)} against {LIBERTY_TT.name}")
    first = next(iter(runs.values()))
    lines.append(f"ngspice: {first['ngspice']['version']}  sha256 {first['ngspice']['sha256']}  image {first['ngspice']['image']}")
    lines.append(f"ramp: {'FULL RAMP = table slew (broken case)' if first['full_ramp'] else 'slew window per the Liberty thresholds'}")
    same = all(r["setup"] == setup for r in runs.values())
    ok &= same
    lines.append(f"setup read from the Liberty: {json.dumps(setup)}")
    lines.append(f"setup used by every run equals the Liberty's: {'yes' if same else 'NO'}")
    errors = [e for r in runs.values() for e in r["errors"]]
    if errors:
        ok = False
        lines.append(f"FAILED MEASUREMENTS: {len(errors)}, first: {errors[0]}")
    sense = [e for e in entries if e["table"] == "timing_sense"]
    if sense:
        ok = False
        lines += [f"timing sense differs: {e['cell']} {e['pin']}: ours {e['ours']}, HD {e['hd']}" for e in sense]

    timed = [e for e in entries if e["table"] != "timing_sense"]
    missing = [e for e in timed if e["error_pct"] is None]
    if missing:
        ok = False
        lines.append(f"entries with no value: {len(missing)}")
    good = [e for e in timed if e["error_pct"] is not None]
    lines.append("")
    lines.append(f"{'cell':10s} {'entries':>7s} {'med |err| delay':>16s} {'med |err| trans':>16s} {'med |err| all':>14s} "
                 f"{'med err (signed)':>16s}  max |err|")
    for cell in runs:
        mine = [e for e in good if e["cell"] == cell]
        if not mine:
            continue
        d = [abs(e["error_pct"]) for e in mine if e["table"].startswith("cell_")]
        t = [abs(e["error_pct"]) for e in mine if e["table"].endswith("_transition")]
        worst = max(mine, key=lambda e: abs(e["error_pct"]))
        lines.append(f"{cell:10s} {len(mine):7d} {statistics.median(d):15.2f}% {statistics.median(t):15.2f}% "
                     f"{statistics.median(d + t):13.2f}% {statistics.median([e['error_pct'] for e in mine]):15.2f}%  "
                     f"{worst['error_pct']:+.1f}% at {worst['pin']} {worst['table']} slew {worst['slew_ns']} load {worst['load_pf']}")
    if good:
        overall = statistics.median(abs(e["error_pct"]) for e in good)
        worst = max(good, key=lambda e: abs(e["error_pct"]))
        passed = overall <= MEDIAN_LIMIT
        ok &= passed
        lines.append("")
        lines.append(f"delay and transition: median |error| {overall:.2f}% over {len(good)} entries "
                     f"(limit {MEDIAN_LIMIT}%): {'PASS' if passed else 'FAIL'}")
        lines.append(f"largest: {worst['error_pct']:+.1f}% at {worst['cell']} {worst['pin']} {worst['table']} "
                     f"slew {worst['slew_ns']} ns load {worst['load_pf']} pF")
    lines.append("")
    for c in caps:
        if c["kind"] != "capacitance":
            continue
        passed = c["error_pct"] is not None and abs(c["error_pct"]) <= CAP_LIMIT
        ok &= passed
        err = "n/a" if c["error_pct"] is None else f"{c['error_pct']:+.1f}%"
        full = next((f for f in caps if f["cell"] == c["cell"] and f["pin"] == c["pin"] and f["kind"] == "capacitance_full"), None)
        note = f"   [whole run: {full['ours']:.6f}, {full['error_pct']:+.1f}%]" if full and full["ours"] is not None else ""
        lines.append(f"capacitance {c['cell']:8s} {c['pin']:3s} ours {c['ours'] or float('nan'):.6f} HD {c['hd']:.6f} pF "
                     f"{err:>7s} (limit {CAP_LIMIT}%): {'PASS' if passed else 'FAIL'}{note}")
    lines.append("")
    lines.append(f"TABLE 5 (delay, transition, capacitance, setup): {'PASS' if ok else 'FAIL'}")
    return lines, ok


def write_csv(path: Path, rows: list[dict]):
    if not rows:
        return
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cells", nargs="*", default=CELLS)
    ap.add_argument("--grid", type=int)
    ap.add_argument("--full-ramp", action="store_true")
    ap.add_argument("--image", default=IMAGE)
    ap.add_argument("--tag", default="")
    ap.add_argument("--no-run", action="store_true", help="compare the timing JSON already in build/char/")
    args = ap.parse_args()
    tag = args.tag or ("_fullramp" if args.full_ramp else "")
    runs, entries, caps = {}, [], []
    for short in args.cells:
        if args.no_run:
            r = json.loads((ROOT / "build/char" / short / f"{PREFIX}{short}_timing{tag}.json").read_text())
        else:
            r = characterize_hd(short, args.grid, args.full_ramp, args.image, tag)
        runs[short] = r
        e, c = compare(short, r)
        entries += e
        caps += c
        print(f"{short}: {len(e)} entries compared")
    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    write_csv(out / f"char_validation{tag}_entries.csv", entries)
    write_csv(out / f"char_validation{tag}_caps.csv", caps)
    lines, ok = summary(entries, caps, runs, tag)
    (out / f"char_validation{tag}.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    sys.exit(0 if ok else 1)
