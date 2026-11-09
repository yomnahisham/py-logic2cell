"""Table 6 cells against their HD counterparts in timing (option 1 handout, section 6): delay and output
slew at the HD table point nearest 100 ps and 10 fF.

    python -m src.cell.table6_timing [--only and2_1,xor2_1]       -> results/table6_timing.csv / .txt
    python -m src.cell.table6_timing --verify nand2_1             -> one-point run against the full grid

Input capacitance is shown too (each pin, measured at the same point): a cell can be faster than HD only
because its input stage is larger, which moves delay into the gate that drives it; Table 6's fixed input
slew does not show that, the capacitance does.

Run after the test cells are characterized (python -m src.cell.char_tests) and src.cell.table6 has written
results/table6_vs_hd.csv (width and area are taken from there).

Both sides are measured by our flow on the same ngspice, so the difference is the cells, not the tools:
  - ours: build/cells/<ours>/<ours>_timing.json, characterized on the HD cell's own table indexes;
  - HD: the installed layout, extracted and characterized by us. A cell with a full-grid run
    (build/char/<hd>/..._timing.json, from char_validate) uses it. For the others only the one point is
    simulated (..._timing_point.json): every transient in a deck is its own `tran` with its own step, ramp
    and stop time, so a one-point run gives the same number as that entry of a full-grid run. --verify
    checks this on a cell that has both.
The shipped Liberty value at the same point is shown beside them for reference.

Pins: our pin k is compared with the HD cell's pin k (pin order of its Liberty cell). The mapping is used
only if the two functions are equal under it (truth tables, src.common.request); otherwise the cell stops
with an error. For pins that are symmetric in the function (A1/A2 of a22oi) the mapping is one of several
valid ones, so a pin pair may sit at different places in the stack; the per-cell summary therefore uses the
worst arc over all pins, which does not depend on that choice.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from src.cell.characterize import CAP_POINT, characterize, hd_grids, nearest
from src.cell.liberty_timing import read_cell, read_setup
from src.cell.stress import stress
from src.cell.table6 import PAIRS
from src.common.request import read_request, truth_table
from src.paths import PREFIX

ROOT = Path(__file__).resolve().parents[2]
TABLES = ("cell_rise", "cell_fall", "rise_transition", "fall_transition")


def request_of(short: str) -> Path:
    for folder in ("test", "hd"):                    # requests/test/ wins, as in char_tests
        p = ROOT / "requests" / folder / f"{short}.json"
        if p.exists():
            return p
    raise FileNotFoundError(f"no request for {short} in requests/test or requests/hd")


def pin_map(ours: list[str], ours_table: int, short: str) -> dict[str, str]:
    """our pin -> HD pin, by position, checked by the functions."""
    hd = read_cell(short)
    if len(ours) != len(hd.inputs):
        raise ValueError(f"{short}: {len(ours)} inputs against HD's {len(hd.inputs)}")
    if truth_table(hd.function, tuple(hd.inputs)) != ours_table:
        raise ValueError(f"{short}: our function differs from HD's {hd.function} with pins {ours} -> {hd.inputs}")
    return dict(zip(ours, hd.inputs))


def point(short: str) -> dict[str, tuple[float, float]]:
    """HD pin -> (slew ns, load pF): the entry of its own table indexes nearest CAP_POINT."""
    hd = read_cell(short)
    out = {}
    for pin, (slews, loads) in hd_grids(short, hd.inputs).items():
        out[pin] = (slews[nearest(slews, CAP_POINT[0])], loads[nearest(loads, CAP_POINT[1])])
    return out


def hd_point_run(short: str, tag: str = "_point") -> dict:
    """Characterize the installed cell at that one point only (same flow as characterize_hd)."""
    from src.cell.compare import hd_reference
    hd = read_cell(short)
    folder = hd_reference(ROOT / "build/char" / short, short)
    stress(folder, hd.name)
    grids = {pin: ([s], [l]) for pin, (s, l) in point(short).items()}
    table = truth_table(hd.function, tuple(hd.inputs))
    return characterize(folder, hd.name, f"{hd.name}_sasb.spice", hd.inputs, hd.output, table, grids,
                        read_setup(), tag=tag)


def at_point(arc: dict, slew: float, load: float) -> dict[str, float | None]:
    """table -> value of one arc at (slew, load), which must be one of its index values."""
    i, j = arc["index_1"].index(slew), arc["index_2"].index(load)
    return {t: v[i][j] for t, v in arc["tables"].items()}


def hd_side(short: str, sha: str, run_missing: bool) -> tuple[dict, str]:
    folder = ROOT / "build/char" / short
    for tag, how in (("", "full grid"), ("_point", "one point")):
        p = folder / f"{PREFIX}{short}_timing{tag}.json"
        if p.exists():
            r = json.loads(p.read_text())
            if r["ngspice"]["sha256"] == sha:
                return r, how
            print(f"{p.name}: made by ngspice {r['ngspice']['sha256'][:8]}, not {sha[:8]}; not used")
    if not run_missing:
        raise FileNotFoundError(f"{short}: no HD run on ngspice {sha[:8]}")
    print(f"{short}: simulating the installed cell at the one point", flush=True)
    r = hd_point_run(short)
    if r["errors"]:
        raise RuntimeError(f"{short}: {r['errors']}")
    return r, "one point"


def compare(ours_name: str, short: str, run_missing: bool = True) -> tuple[list[dict], dict]:
    req = read_request(request_of(ours_name.removeprefix("dd2_gc1__")))
    ours = json.loads((ROOT / "build/cells" / req.name / f"{req.name}_timing.json").read_text())
    if ours["grid_from"] != PREFIX + short:
        raise ValueError(f"{req.name} was characterized on {ours['grid_from']}'s grid, not {PREFIX}{short}'s")
    pins = pin_map(list(req.inputs), req.truth_table, short)
    hd, how = hd_side(short, ours["ngspice"]["sha256"], run_missing)
    lib = read_cell(short)
    lib_arcs = {a.pin: a for a in lib.arcs if not a.when}
    hd_arcs = {a["pin"]: a for a in hd["arcs"]}
    where = point(short)
    rows = []
    for arc in ours["arcs"]:
        hp = pins[arc["pin"]]
        slew, load = where[hp]
        mine, theirs = at_point(arc, slew, load), at_point(hd_arcs[hp], slew, load)
        lt = lib_arcs[hp].tables
        for t in TABLES:
            if t not in mine:
                continue
            shipped = lt[t]["values"][lt[t]["index_1"].index(slew)][lt[t]["index_2"].index(load)]
            v, h = mine[t], theirs[t]
            rows.append(dict(cell=req.name, hd=PREFIX + short, pin=arc["pin"], hd_pin=hp, table=t,
                             slew_ns=slew, load_pf=load, sense_ours=arc["sense"], sense_hd=hd_arcs[hp]["sense"],
                             ours_ns=v, hd_our_flow_ns=h, hd_shipped_ns=shipped,
                             diff_pct=(v - h) / h * 100, hd_run=how))
    for pin, hp in pins.items():
        v, h = ours["pins"][pin]["capacitance"], hd["pins"][hp]["capacitance"]
        rows.append(dict(cell=req.name, hd=PREFIX + short, pin=pin, hd_pin=hp, table="capacitance",
                         slew_ns=ours["pins"][pin]["at"]["slew_ns"], load_pf=ours["pins"][pin]["at"]["load_pf"],
                         sense_ours="", sense_hd="", ours_ns="", hd_our_flow_ns="",
                         hd_shipped_ns="", diff_pct=(v - h) / h * 100, hd_run=how,
                         ours_pf=v, hd_our_flow_pf=h, hd_shipped_pf=lib.capacitance[hp]["capacitance"]))
    worst = lambda key, kinds: max((r for r in rows if r["table"] in kinds), key=lambda r: r[key])
    summary = dict(cell=req.name, hd=PREFIX + short, pins=" ".join(f"{a}->{b}" for a, b in pins.items()),
                   hd_run=how, ngspice_sha256=ours["ngspice"]["sha256"])
    for name, kinds in (("delay", ("cell_rise", "cell_fall")), ("slew", ("rise_transition", "fall_transition"))):
        o, h, s = worst("ours_ns", kinds), worst("hd_our_flow_ns", kinds), worst("hd_shipped_ns", kinds)
        summary.update({f"{name}_ours_ps": round(o["ours_ns"] * 1e3, 2),
                        f"{name}_ours_arc": f"{o['pin']} {o['table']}",
                        f"{name}_hd_ps": round(h["hd_our_flow_ns"] * 1e3, 2),
                        f"{name}_hd_arc": f"{h['hd_pin']} {h['table']}",
                        f"{name}_diff_pct": round((o["ours_ns"] - h["hd_our_flow_ns"]) / h["hd_our_flow_ns"] * 100, 1),
                        f"{name}_hd_shipped_ps": round(s["hd_shipped_ns"] * 1e3, 2)})
    caps = [r for r in rows if r["table"] == "capacitance"]
    o, h = max(caps, key=lambda r: r["ours_pf"]), max(caps, key=lambda r: r["hd_our_flow_pf"])
    s = max(caps, key=lambda r: r["hd_shipped_pf"])
    summary.update(cap_ours_ff=round(o["ours_pf"] * 1e3, 3), cap_ours_pin=o["pin"],
                   cap_hd_ff=round(h["hd_our_flow_pf"] * 1e3, 3), cap_hd_pin=h["hd_pin"],
                   cap_diff_pct=round((o["ours_pf"] - h["hd_our_flow_pf"]) / h["hd_our_flow_pf"] * 100, 1),
                   cap_hd_shipped_ff=round(s["hd_shipped_pf"] * 1e3, 3))
    return rows, summary


def area_rows() -> dict[str, dict]:
    path = ROOT / "results/table6_vs_hd.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing: run python -m src.cell.table6 first")
    with path.open() as f:
        return {r["cell"]: r for r in csv.DictReader(f)}


def verify(short: str) -> None:
    """One-point run of an HD cell that has a full-grid run: both must give the same numbers."""
    full = json.loads((ROOT / "build/char" / short / f"{PREFIX}{short}_timing.json").read_text())
    one = hd_point_run(short, tag="_pointcheck")
    if one["ngspice"]["sha256"] != full["ngspice"]["sha256"]:
        print(f"note: full grid on ngspice {full['ngspice']['sha256'][:8]}, this run on "
              f"{one['ngspice']['sha256'][:8]}; differences of up to 0.064% are the build, not the method")
    worst = 0.0
    for a, b in zip(sorted(full["arcs"], key=lambda a: a["pin"]), sorted(one["arcs"], key=lambda a: a["pin"])):
        s, l = b["index_1"][0], b["index_2"][0]
        x, y = at_point(a, s, l), at_point(b, s, l)
        for t in x:
            d = (y[t] - x[t]) / x[t] * 100
            worst = max(worst, abs(d))
            print(f"  {a['pin']:3s} {t:16s} full grid {x[t]:.6f}  one point {y[t]:.6f} ns  ({d:+.4f}%)")
    print(f"{short}: largest difference {worst:.4f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated Table 6 cells, e.g. and2_1,xor2_1")
    ap.add_argument("--no-run", action="store_true", help="use existing HD runs only; never start ngspice")
    ap.add_argument("--verify", metavar="HD", help="check a one-point run against the full grid, e.g. nand2_1")
    args = ap.parse_args()
    if args.verify:
        verify(args.verify)
        return

    pairs = [(f"dd2_gc1__{o}", h) for o, h, _ in PAIRS]
    if args.only:
        keep = set(args.only.split(","))
        pairs = [(o, h) for o, h in pairs if o.removeprefix("dd2_gc1__") in keep]
    areas = area_rows()
    rows, summaries, failed = [], [], []
    for ours, short in pairs:
        try:
            r, s = compare(ours, short, run_missing=not args.no_run)
        except Exception as e:                        # keep going; the cell is reported as failed
            failed.append(f"{ours}: {type(e).__name__}: {e}")
            continue
        a = areas[ours]
        s.update(sites_ours=a["sites_ours"], sites_hd=a["sites_hd"], area_ours_um2=a["area_ours_um2"],
                 area_hd_um2=a["area_hd_um2"])
        rows += r
        summaries.append(s)

    out = ROOT / "results"
    with (out / "table6_timing_arcs.csv").open("w", newline="") as f:
        fields = list(dict.fromkeys(k for r in rows for k in r))
        w = csv.DictWriter(f, fieldnames=fields, restval="")
        w.writeheader()
        w.writerows(rows)
    with (out / "table6_timing.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summaries[0]))
        w.writeheader()
        w.writerows(summaries)

    lines = [f"Table 6 against HD (section 6): worst arc over all pins at the HD table point nearest "
             f"{CAP_POINT[0] * 1e3:g} ps / {CAP_POINT[1] * 1e3:g} fF; HD measured by our flow, [shipped Liberty]",
             f"ngspice sha256 {summaries[0]['ngspice_sha256']}", "",
             f"{'cell':22s} {'sites':>7s} {'area um2':>17s}  {'delay ps ours/HD':>22s} {'diff':>7s} {'[shipped]':>9s}"
             f"  {'slew ps ours/HD':>22s} {'diff':>7s} {'[shipped]':>9s}  {'max pin cap fF ours/HD':>22s} {'diff':>7s} "
             f"{'[shipped]':>9s}  HD run"]
    for s in summaries:
        lines.append(f"{s['cell'].removeprefix('dd2_gc1__'):22s} {s['sites_ours']:>3s}/{s['sites_hd']:<3s} "
                     f"{s['area_ours_um2']:>8s}/{s['area_hd_um2']:<8s}  "
                     f"{s['delay_ours_ps']:>10.2f}/{s['delay_hd_ps']:<11.2f} {s['delay_diff_pct']:>+6.1f}% "
                     f"[{s['delay_hd_shipped_ps']:7.2f}]  "
                     f"{s['slew_ours_ps']:>10.2f}/{s['slew_hd_ps']:<11.2f} {s['slew_diff_pct']:>+6.1f}% "
                     f"[{s['slew_hd_shipped_ps']:7.2f}]  "
                     f"{s['cap_ours_ff']:>10.3f}/{s['cap_hd_ff']:<11.3f} {s['cap_diff_pct']:>+6.1f}% "
                     f"[{s['cap_hd_shipped_ff']:7.3f}]  {s['hd_run']}")
    lines += ["", "pins (ours->HD), and the worst arcs:"]
    lines += [f"  {s['cell']}: {s['pins']}; delay {s['delay_ours_arc']} / HD {s['delay_hd_arc']}; "
              f"slew {s['slew_ours_arc']} / HD {s['slew_hd_arc']}; largest cap {s['cap_ours_pin']} / HD {s['cap_hd_pin']}"
              for s in summaries]
    lines += ["", "input capacitance per pin, fF, ours/HD (largest difference first):"]
    for s in summaries:
        mine = sorted((r for r in rows if r["cell"] == s["cell"] and r["table"] == "capacitance"),
                      key=lambda r: -abs(r["diff_pct"]))
        lines.append(f"  {s['cell'].removeprefix('dd2_gc1__'):16s} " + "  ".join(
            f"{r['pin']}->{r['hd_pin']} {r['ours_pf'] * 1e3:.2f}/{r['hd_our_flow_pf'] * 1e3:.2f} ({r['diff_pct']:+.0f}%)"
            for r in mine))
    senses = [r for r in rows if r["sense_ours"] != r["sense_hd"]]
    lines += [f"  timing sense differs: {r['cell']} {r['pin']} ours {r['sense_ours']}, HD {r['sense_hd']}"
              for r in {(r['cell'], r['pin']): r for r in senses}.values()]
    lines += [f"FAILED {f}" for f in failed]
    lines += ["", f"{len(summaries)} of {len(pairs)} Table 6 cells compared: {'PASS' if not failed else 'FAIL'}"]
    (out / "table6_timing.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
