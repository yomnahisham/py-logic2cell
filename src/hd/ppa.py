"""Power, performance and area of each required design, before and after the new cells (option 2 handout,
section 7: area and worst delay; power is our addition).

    python -m src.hd.ppa [--period 10] [--activity 0.1]     -> results/hd/ppa.csv, results/hd/ppa.txt

For each design the script (A or B) with the smaller area is taken, per library (best of both, as Table 5):
  reduced  hd_reduced.lib, the baseline;
  real     the same plus Option 1's delivered final-set cells.
Area is the mapped netlist's (`stat -liberty`), worst delay from OpenSTA as src.hd.sta times it, and power from
OpenSTA's report_power on the same netlist at one clock period and switching activity for every design (the
numbers compare libraries, not designs; they are not a power sign-off).

HD's cells carry SkyWater's power tables. Ours carry none in their delivered Liberty (src.cell.liberty_write,
WRITE_POWER): for this measurement only, their groups are rewritten with the power our characterizer measured,
into build/libs/hd_reduced_real_power.lib. Against HD that power is off by 0.79% on inv_1 and 15 to 19% on the
multi-input cells, and leakage by 2 to 4x (results/power_validation.txt), so the power of our cells is reported
apart: their share of each design's total, and the total's uncertainty from them (20% of their internal and
switching power, 4x their leakage).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from src.cell.liberty_write import cell_group
from src.cell.model_check import cell_group as group_text
from src.hd.liberty_writer import EXTENDED_REAL
from src.hd.sta import LIBRARIES, WORK, clocks, sta, time_design
from src.hd.liberty import cell_areas
from src.map_library.table1 import DESIGNS, NETLIST_OUT
from src.common.request import read_request
from src.paths import ROOT

POWER_LIB = ROOT / "build/libs/hd_reduced_real_power.lib"
OUT = ROOT / "results/hd"
INTERNAL_ERR, LEAKAGE_ERR = 0.20, 4.0        # from results/power_validation.txt (see the docstring)


def power_library() -> tuple[Path, list[str]]:
    """The real library with our cell groups rewritten with their measured power; the cells it holds."""
    text = EXTENDED_REAL.read_text()
    ours = []
    for name in json.loads((OUT / "final_set.json").read_text())["cells"]:
        if f'cell ("{name}")' not in text and f"cell ({name})" not in text:
            continue
        timing = json.loads((ROOT / "build/cells" / name / f"{name}_timing.json").read_text())
        if not timing.get("leakage_nw") or not all(a.get("power") for a in timing["arcs"]):
            raise SystemExit(f"{name}: its characterization has no power; run src.cell.deliver on it again")
        response = json.loads((ROOT / "cells" / name / "response.json").read_text())
        request = read_request(ROOT / "requests/candidates" / f"{name}.json")
        new = cell_group(timing, response["area_um2"], request.expression, power=True)
        text = text.replace(group_text(text, name), new)
        ours.append(name)
    POWER_LIB.parent.mkdir(parents=True, exist_ok=True)
    POWER_LIB.write_text(text)
    return POWER_LIB, ours


def area(netlist: Path, lib_text_areas: dict) -> float:
    """Total cell area of a mapped netlist, from the library's areas."""
    total = 0.0
    for cell in re.findall(r"^\s*(\S+)\s+\S+\s*\(", netlist.read_text(), re.M):
        if cell in lib_text_areas:
            total += lib_text_areas[cell][0] or 0.0
    return round(total, 4)


def power(netlist: Path, lib: Path, top: str, ports: list[str], period: float, activity: float, ours: list[str]) -> dict:
    lines = [f"read_liberty {lib}", f"read_verilog {netlist}", f"link_design {top}"]
    lines += [f"create_clock -name {p} -period {period} [get_ports {p}]" for p in ports]
    lines += [f"set_power_activity -global -activity {activity}", "report_power -digits 6"]
    if ours:
        lines.append('set mine [get_cells -quiet -filter "ref_name =~ dd2_gc1__*"]')
        lines.append('if {[llength $mine]} { report_power -instances $mine -digits 6 }')
    out = sta("\n".join(lines) + "\nexit\n", WORK / f"{netlist.stem}.power.log")
    total = re.search(r"^Total\s+([-\d.e+]+)\s+([-\d.e+]+)\s+([-\d.e+]+)\s+([-\d.e+]+)", out, re.M)
    if not total:
        raise RuntimeError(f"no power total for {netlist.name}, see {WORK / (netlist.stem + '.power.log')}")
    internal, switching, leakage, tot = map(float, total.groups())
    mine = [list(map(float, m)) for m in re.findall(r"^\s*([-\d.e+]+)\s+([-\d.e+]+)\s+([-\d.e+]+)\s+([-\d.e+]+)\s+\S+\s*$",
                                                     out.split("report_power -instances")[-1] if ours else "", re.M)]
    # instance rows follow the group table; the group table's own rows start with a name, so they do not match
    m_int = sum(r[0] for r in mine) if mine else 0.0
    m_sw = sum(r[1] for r in mine) if mine else 0.0
    m_leak = sum(r[2] for r in mine) if mine else 0.0
    return dict(power_w=tot, internal_w=internal, switching_w=switching, leakage_w=leakage,
                ours_w=m_int + m_sw + m_leak, ours_instances=len(mine),
                uncertainty_w=INTERNAL_ERR * (m_int + m_sw) + LEAKAGE_ERR * m_leak)


def main(argv: list[str]):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--period", type=float, default=10.0, help="ns, every design's clock for power")
    ap.add_argument("--activity", type=float, default=0.1, help="toggles per clock cycle, every net")
    args = ap.parse_args(argv)
    lib, ours = power_library()
    libs = {"reduced": LIBRARIES["reduced"], "real": LIBRARIES["real"]}
    seq = {n for n, (_, s) in cell_areas(libs["reduced"].read_text()).items() if s}
    rows = []
    for design, top in DESIGNS.items():
        for tag, timing_lib in libs.items():
            areas = cell_areas(timing_lib.read_text())
            best = None
            for script in "AB":
                t = time_design(design, top, tag, script, seq)          # maps the netlist if it is missing
                netlist = NETLIST_OUT / f"{design}_{tag}_{script}.v"
                a = area(netlist, areas)
                if best is None or a < best[0]:
                    best = (a, script, t, netlist)
            a, script, t, netlist = best
            ports = clocks(netlist.read_text(), seq)
            p = power(netlist, lib if tag == "real" else timing_lib, top, ports, args.period, args.activity,
                      ours if tag == "real" else [])
            rows.append(dict(design=design, library=tag, script=script, area_um2=a, worst_delay_ns=t["worst_delay_ns"],
                             **{k: (f"{v:.6e}" if isinstance(v, float) else v) for k, v in p.items()}))
    with (OUT / "ppa.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    lines = [f"PPA of the required designs, best of scripts A and B by area; power at {args.period} ns and activity "
             f"{args.activity} on every net (OpenSTA report_power), our cells' power from build/libs/hd_reduced_real_power.lib",
             f"{'design':10s} {'area um2':>22s} {'worst delay ns':>20s} {'power mW':>24s}  our cells' share (+-)"]
    by = {(r["design"], r["library"]): r for r in rows}
    for design in DESIGNS:
        b, r = by[(design, "reduced")], by[(design, "real")]
        pct = lambda x, y: (float(y) - float(x)) / float(x) * 100
        lines.append(f"{design:10s} {b['area_um2']:>9} -> {r['area_um2']:>9} ({pct(b['area_um2'], r['area_um2']):+.2f}%) "
                     f"{b['worst_delay_ns']:>6} -> {r['worst_delay_ns']:>6} ({pct(b['worst_delay_ns'], r['worst_delay_ns']):+.1f}%) "
                     f"{float(b['power_w']) * 1e3:8.4f} -> {float(r['power_w']) * 1e3:8.4f} ({pct(b['power_w'], r['power_w']):+.2f}%)  "
                     f"{float(r['ours_w']) / float(r['power_w']) * 100:.2f}% (+-{float(r['uncertainty_w']) / float(r['power_w']) * 100:.2f}%)")
    tb = sum(float(by[(d, 'reduced')]['area_um2']) for d in DESIGNS); tr = sum(float(by[(d, 'real')]['area_um2']) for d in DESIGNS)
    pb = sum(float(by[(d, 'reduced')]['power_w']) for d in DESIGNS); pr = sum(float(by[(d, 'real')]['power_w']) for d in DESIGNS)
    lines.append(f"{'total':10s} {tb:.4f} -> {tr:.4f} um2 ({(tr - tb) / tb * 100:+.2f}%), power {pb * 1e3:.4f} -> {pr * 1e3:.4f} mW "
                 f"({(pr - pb) / pb * 100:+.2f}%)")
    (OUT / "ppa.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1:])
