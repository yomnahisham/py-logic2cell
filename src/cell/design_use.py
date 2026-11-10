"""Step 9 of the option 1 handout: a small design mapped onto HD plus our cells, simulated at gate level and
timed (also checkpoint 3: "a small design mapped onto HD plus your cells, simulated and timed").

    python -m src.cell.design_use <Tutorial 4 folder>     -> results/design_use.txt, build/design_use/

The design is Tutorial 4's SPM with its self-checking testbench SPM_tb.v. The library is the HD Liberty with
the cell group of every delivered cell of ours appended (cells/*/cell.lib whose response passed). Two maps:
  free     ABC picks from HD and ours alike;
  forced   HD's cells of the functions we deliver are dont_use (every drive, e.g. nand2_*), so every such
           function in the design has to be one of our cells.
Each netlist is simulated with Icarus (Tutorial 4's gate-level run: the PDK's cell models plus our cell.v)
and timed with OpenSTA (as spm_design.py), with the clock, driving cell and load of Tutorial 4.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from src.cell import spm_design
from src.cell.deliver import hd_twin
from src.cell.model_check import cell_group
from src.cell.spm_design import DONT_USE, copy_sources, synthesize, time_it, tutorial_settings, yosys_version
from src.common.request import read_request
from src.hd.liberty_writer import extend
from src.paths import LIB, LIBERTY_TT, PREFIX

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "build/design_use"
REQUESTS = ["requests/hd", "requests/test", "requests/candidates"]
MODELS = [LIB / "verilog/primitives.v", LIB / "verilog/sky130_fd_sc_hd.v"]


def delivered() -> list:
    """(request, cell folder) of every cell whose build passed and that has a Liberty cell."""
    out = {}
    for folder in REQUESTS:
        for path in sorted((ROOT / folder).glob("*.json")):
            r = read_request(path)
            cell = ROOT / "cells" / r.name
            if (cell / "cell.lib").exists() and json.loads((cell / "response.json").read_text())["status"] == "pass":
                out[r.name] = (r, cell)
    return list(out.values())


def library(cells: list) -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    groups = "".join(cell_group((c / "cell.lib").read_text(), r.name) for r, c in cells)
    path = WORK / "hd_plus_ours.lib"
    path.write_text(extend(LIBERTY_TT.read_text(), groups))
    return path


def simulate(netlist: Path, cells: list, tut: Path, tag: str) -> dict:
    """Tutorial 4's gate-level run (make gls): the self-checking testbench on the netlist."""
    out = WORK / tag / "spm_gl"
    cmd = ["iverilog", "-DFUNCTIONAL", "-DUNIT_DELAY=", "-s", "SPM_tb", "-o", str(out), str(tut / "SPM_tb.v"),
           str(netlist), *map(str, MODELS), *(str(c / "cell.v") for _, c in cells)]
    subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=WORK / tag)
    run = subprocess.run(["vvp", "-n", str(out)], capture_output=True, text=True, cwd=WORK / tag)
    (WORK / tag / "gls.log").write_text(run.stdout + run.stderr)
    return {"pass": run.returncode == 0 and "PASS:" in run.stdout,
            "line": next((l for l in run.stdout.splitlines() if l.startswith(("PASS", "FAIL", "ERROR"))), "no result")}


def ours_used(netlist: Path) -> dict:
    found = re.findall(r"^\s*(dd2_\w+)\s", netlist.read_text(), re.M)
    return {name: found.count(name) for name in sorted(set(found))}


if __name__ == "__main__":
    spm_design.WORK = WORK      # spm_design's steps write under build/design_use/ for this run
    tut_given = Path(sys.argv[1]).expanduser().resolve()
    tut = copy_sources(tut_given)
    (tut / "SPM_tb.v").write_text((tut_given / "SPM_tb.v").read_text())
    cells = delivered()
    lib = library(cells)
    settings = tutorial_settings(tut)
    twins = sorted({hd_twin(r.inputs, r.truth_table)[0] for r, _ in cells if hd_twin(r.inputs, r.truth_table)})
    forced = DONT_USE + "".join(f" -dont_use {PREFIX}{t.rsplit('_', 1)[0]}_*" for t in twins)
    lines = [f"SPM on HD plus our cells: {yosys_version()}; OpenSTA in the dd2-opensta image; Icarus "
             + subprocess.run(["iverilog", "-V"], capture_output=True, text=True).stdout.splitlines()[0],
             f"library {lib.relative_to(ROOT)}: HD and {len(cells)} cells of ours: {', '.join(r.name for r, _ in cells)}",
             f"forced: HD cells dont_use for the functions we deliver: {', '.join(t.rsplit('_', 1)[0] + '_*' for t in twins)}",
             f"Tutorial 4 settings: ABC -D {settings['period_ps']} ps (clock period), driving cell "
             f"{settings['driving_cell']}, output load {settings['load_ff']} fF", ""]
    ok = True
    for tag, dont_use in (("free", DONT_USE), ("forced", forced)):
        netlist = synthesize(tut, lib, tag, settings, dont_use)
        timing = time_it(netlist, lib, tag, settings)
        sim = simulate(netlist, cells, tut, tag)
        used = ours_used(netlist)
        ok &= sim["pass"]
        lines += [f"{tag}: {sum(used.values())} instances of our cells {used or ''}",
                  f"    gate-level simulation: {sim['line']}",
                  f"    OpenSTA: worst path {timing['arrival_ns']:.4f} ns, slack {timing['slack_ns']:+.4f} ns "
                  f"({timing['start']} -> {timing['end']}); area {timing['area']} um2"]
    lines += ["", "for the HD-only baseline of the same flow see results/spm_design_level.txt (row hd)"]
    (ROOT / "results/design_use.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    raise SystemExit(0 if ok else 1)
