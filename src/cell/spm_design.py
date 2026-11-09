"""The design-level row of Table 5 (option 1 handout, section 5.1): Tutorial 4's SPM, mapped and timed with
the HD Liberty and with a copy of it in which the six reference cells are ours.

    python -m src.cell.spm_design <Tutorial 4 folder with SPM.v, CSADD.v, TCMP.v, synth.ys, abc_constr.txt>

Three runs, each with Yosys (the host's, as Tutorial 4 needs >= 0.34 for -dont_use) and OpenSTA (dd2-opensta):
  hd         SPM mapped onto the HD Liberty, timed with it (the baseline);
  ours       SPM mapped again onto build/sta/hd_tt_ours.lib (HD with our six cells, liberty_write validation),
             timed with it: the row Table 5 asks for;
  hd_on_ours the netlist of `hd`, timed with our library: the same gates, so any change is our cells' timing
             and not a different choice by ABC.
The mapping follows Tutorial 4's synth.ys; its ABC delay target (-D) and its abc_constr.txt (driving cell and
output load) are read from the tutorial's files, and the clock period for OpenSTA is that same target. Writes
results/spm_design_level.txt and keeps the netlists and logs in build/spm/.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

from src.cell.tools import STA_IMAGE, run
from src.paths import LIBERTY_TT

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "build/spm"
OURS = ROOT / "build/sta/hd_tt_ours.lib"
SOURCES = ["SPM.v", "CSADD.v", "TCMP.v"]
DONT_USE = "-dont_use sky130_fd_sc_hd__lpflow_* -dont_use sky130_fd_sc_hd__macro_sparecell"   # as in synth.ys


def tutorial_settings(tut: Path) -> dict:
    """ABC's delay target (ps) from synth.ys, and the driving cell and load from abc_constr.txt."""
    target = re.search(r"^\s*abc\s.*-D\s+(\d+)", (tut / "synth.ys").read_text(), re.M)
    constr = (tut / "abc_constr.txt").read_text()
    cell = re.search(r"set_driving_cell\s+(\S+)", constr)
    load = re.search(r"set_load\s+([\d.]+)", constr)
    if not (target and cell and load):
        raise ValueError(f"{tut}: could not read -D from synth.ys or the constraints from abc_constr.txt")
    # `yosys -h abc`: "the set_load statement sets the load in femtofarads"; OpenSTA takes the Liberty's unit, pF
    return {"period_ps": int(target[1]), "driving_cell": cell[1], "load_ff": float(load[1])}


def yosys_version() -> str:
    out = subprocess.run(["yosys", "-V"], text=True, stdout=subprocess.PIPE).stdout.strip()
    m = re.search(r"Yosys (\d+)\.(\d+)", out)
    if not m or (int(m[1]), int(m[2])) < (0, 34):
        raise RuntimeError(f"Tutorial 4's mapping needs Yosys >= 0.34 for -dont_use; found {out!r}")
    return out


def synthesize(tut: Path, lib: Path, tag: str, settings: dict, dont_use: str = DONT_USE) -> Path:
    folder = WORK / tag
    folder.mkdir(parents=True, exist_ok=True)
    netlist = folder / f"SPM.{tag}.gl.v"
    script = [f"read_verilog {' '.join(str(tut / s) for s in SOURCES)}", "hierarchy -check -top SPM", "proc", "opt",
              "synth -top SPM", "flatten", "opt",
              f"dfflibmap -liberty {lib}",
              f"abc -D {settings['period_ps']} -constr {tut / 'abc_constr.txt'} -liberty {lib} {dont_use}",
              "opt_clean -purge", f"write_verilog -noattr -noexpr {netlist}",
              f"tee -o {folder / 'stat.txt'} stat -liberty {lib}"]
    (folder / "synth.ys").write_text("\n".join(script) + "\n")
    p = subprocess.run(["yosys", "-q", "-l", str(folder / "synth.log"), "-s", str(folder / "synth.ys")], text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if p.returncode:
        raise RuntimeError(f"yosys failed for {tag}, see {folder / 'synth.log'}")
    return netlist


def time_it(netlist: Path, lib: Path, tag: str, settings: dict) -> dict:
    folder = WORK / tag
    folder.mkdir(parents=True, exist_ok=True)
    period = settings["period_ps"] / 1000
    lib = lib.resolve()     # the container mounts only the final target of the pdk link (tools.run)
    script = "\n".join([
        f"read_liberty {lib}", f"read_verilog {netlist}", "link_design SPM",
        f"create_clock -name clk -period {period} [get_ports clk]",
        "set inputs [delete_from_list [all_inputs] [get_ports clk]]",
        "set_input_delay 0 -clock clk $inputs", "set_output_delay 0 -clock clk [all_outputs]",
        f"set_driving_cell -lib_cell {settings['driving_cell']} $inputs",
        f"set_load {settings['load_ff'] / 1000} [all_outputs]",
        "report_checks -path_delay max -digits 4",
        "report_worst_slack -max -digits 4",
        "exit"]) + "\n"
    (folder / "sta.tcl").write_text(script)
    out = run("sta", ["-no_init", "-no_splash", "-exit"], ROOT, folder / "sta.log", stdin=script, image=STA_IMAGE)
    # report_checks prints one path per group; the asynchronous reset (recovery) group comes first, and the
    # design's worst delay is the clock group's register-to-register path
    block = next((b for b in out.split("Startpoint:")[1:] if re.search(r"Path Group:\s*clk\b", b)), None)
    if block is None:
        raise RuntimeError(f"OpenSTA reported no path in the clk group for {tag}, see {folder / 'sta.log'}")
    block = "Startpoint:" + block
    arrival = re.search(r"([-\d.]+)\s+data arrival time", block)
    slack = re.search(r"([-\d.]+)\s+slack \((?:MET|VIOLATED)\)", block)
    start = re.search(r"Startpoint:\s*(\S+)", block)
    end = re.search(r"Endpoint:\s*(\S+)", block)
    if not (arrival and slack):
        raise RuntimeError(f"OpenSTA gave no path for {tag}, see {folder / 'sta.log'}")
    cells = re.findall(r"sky130_fd_sc_hd__\w+", netlist.read_text())
    return {"tag": tag, "arrival_ns": float(arrival[1]), "slack_ns": float(slack[1]),
            "start": start[1] if start else "?", "end": end[1] if end else "?", "cells": len(cells),
            "area": re.search(r"Chip area for module .*?:\s*([\d.]+)", (netlist.parent / "stat.txt").read_text())[1]
            if (netlist.parent / "stat.txt").exists() else "-"}


def copy_sources(tut: Path) -> Path:
    """The design and abc_constr.txt, copied into build/spm/src/: a path Yosys reads without quoting (the
    tutorial folder may have spaces in its name), and a record of the files this run used."""
    src = WORK / "src"
    src.mkdir(parents=True, exist_ok=True)
    for name in SOURCES + ["abc_constr.txt", "synth.ys"]:
        shutil.copy(tut / name, src / name)
    return src


if __name__ == "__main__":
    tut = copy_sources(Path(sys.argv[1]).expanduser().resolve())
    if not OURS.exists():
        sys.exit(f"{OURS} is missing: run python -m src.cell.liberty_write validation first")
    settings = tutorial_settings(tut)
    version = yosys_version()
    hd_net = synthesize(tut, LIBERTY_TT, "hd", settings)
    ours_net = synthesize(tut, OURS, "ours", settings)
    runs = [time_it(hd_net, LIBERTY_TT, "hd", settings), time_it(ours_net, OURS, "ours", settings),
            time_it(hd_net, OURS, "hd_on_ours", settings)]
    base = runs[0]["arrival_ns"]
    lines = [f"SPM design level (Table 5): {version}; OpenSTA in {STA_IMAGE}",
             f"settings from Tutorial 4's files (copied to {tut.relative_to(ROOT)}): ABC -D {settings['period_ps']} ps (also the clock period), driving cell "
             f"{settings['driving_cell']}, output load {settings['load_ff']} fF",
             f"ours = {OURS.relative_to(ROOT)} (HD with the six reference cells replaced by our characterization)", ""]
    for r in runs:
        lines.append(f"{r['tag']:11s} worst path {r['arrival_ns']:.4f} ns ({(r['arrival_ns'] - base) / base * 100:+.2f}% "
                     f"against hd), worst slack {r['slack_ns']:+.4f} ns, {r['cells']} cells, area {r['area']} um2, "
                     f"{r['start']} -> {r['end']}")
    lines += ["", f"change in worst delay, remapped onto our cells (Table 5): "
              f"{(runs[1]['arrival_ns'] - base) * 1000:+.1f} ps ({(runs[1]['arrival_ns'] - base) / base * 100:+.2f}%)",
              f"same netlist, our cells' timing only: "
              f"{(runs[2]['arrival_ns'] - base) * 1000:+.1f} ps ({(runs[2]['arrival_ns'] - base) / base * 100:+.2f}%)"]
    (ROOT / "results/spm_design_level.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
