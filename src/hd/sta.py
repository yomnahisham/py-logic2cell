"""Worst delay of each design from OpenSTA (option 2 handout, section 7), on the reduced library and
on the library with the new cells, so that a saving bought with a large delay penalty is visible.

Each mapped netlist (build/netlists/<design>_<library>_<script>.v, mapped first if missing) is timed
with the Liberty it was mapped onto, in the dd2-opensta container. The clocks are the input ports that
drive a flip-flop's or latch's clock pin; each gets a clock of PERIOD, and the other inputs and the
outputs are constrained to the first clock with zero delay, so every path is timed: input to
register, register to register, register to output and input to output. Inputs are ideal (no driving
cell) and outputs carry no load. The worst delay is the largest data arrival time OpenSTA reports.
The new cells' timing is a placeholder (src.hd.liberty_writer) until real cells replace them, so
their delays are indicative only.

    python -m src.hd.sta [--libraries reduced extended ...]   -> results/hd/sta.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.hd.liberty import cell_areas
from src.hd.liberty_writer import EXTENDED, EXTENDED_REAL
from src.map_library.table1 import DESIGNS, LIBS, NETLIST_OUT, map_design
from src.paths import ROOT

IMAGE = os.getenv("STA_IMAGE", "dd2-opensta")
PERIOD = 100.0      # ns; long enough not to matter: the worst delay does not depend on it
LIBRARIES = {"reduced": ROOT / LIBS["reduced"], "extended": EXTENDED, "real": EXTENDED_REAL}
CLOCK_PINS = ("CLK", "CLK_N", "GATE", "GATE_N")
WORK = ROOT / "build/sta_designs"
OUT = ROOT / "results/hd/sta.csv"


def sta(script: str, log: Path) -> str:
    """Run OpenSTA in its container on a Tcl script; returns its output and writes it to log."""
    mount = Path(os.path.commonpath([ROOT, (ROOT / "given").resolve()]))
    cmd = ["docker", "run", "--rm", "-i", "--user", f"{os.getuid()}:{os.getgid()}", "-v", f"{mount}:{mount}",
           "-w", str(ROOT), IMAGE, "sta", "-no_init", "-no_splash", "-exit"]
    p = subprocess.run(cmd, input=script, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log.write_text(p.stdout)
    if p.returncode:
        raise RuntimeError(f"OpenSTA exited with {p.returncode}, see {log}")
    return p.stdout


def clocks(netlist: str, sequential: set[str]) -> list[str]:
    """Input ports wired to the clock pin of a flip-flop or latch."""
    inputs = set(re.findall(r"^\s*input\s+(?:\[[^\]]*\]\s*)?(\S+?)\s*;", netlist, re.M))
    nets = set()
    for cell, body in re.findall(r"^\s*(\S+)\s+\S+\s*\((.*?)\);", netlist, re.M | re.S):
        if cell in sequential:
            nets |= {net.strip() for pin, net in re.findall(r"\.(\w+)\(([^)]*)\)", body) if pin in CLOCK_PINS}
    return sorted(nets & inputs)


def script(netlist: Path, lib: Path, top: str, clock_ports: list[str]) -> str:
    lines = [f"read_liberty {lib}", f"read_verilog {netlist}", f"link_design {top}"]
    for port in clock_ports:
        lines.append(f"create_clock -name {port} -period {PERIOD} [get_ports {port}]")
    if clock_ports:
        lines += [f"set_input_delay 0 -clock {clock_ports[0]} "
                  f"[delete_from_list [all_inputs] [get_ports {{{' '.join(clock_ports)}}}]]",
                  f"set_output_delay 0 -clock {clock_ports[0]} [all_outputs]"]
    lines.append("report_checks -path_delay max -digits 4" + ("" if clock_ports else " -unconstrained"))
    return "\n".join(lines) + "\n"


def worst(report: str) -> dict:
    """The path with the largest data arrival time in a report_checks output."""
    paths = []
    for block in re.split(r"(?=Startpoint:)", report)[1:]:
        arrival = re.search(r"([-\d.]+)\s+data arrival time", block)
        if arrival:
            paths.append((float(arrival[1]), re.search(r"Startpoint:\s*(\S+)", block)[1],
                           re.search(r"Endpoint:\s*(\S+)", block)[1]))
    if not paths:
        raise RuntimeError("OpenSTA reported no path")
    delay, start, end = max(paths)
    return dict(worst_delay_ns=delay, startpoint=start, endpoint=end)


def time_design(design: str, top: str, tag: str, script_name: str, sequential: set[str]) -> dict:
    lib = LIBRARIES[tag]
    netlist = NETLIST_OUT / f"{design}_{tag}_{script_name}.v"
    if not netlist.exists():
        map_design(design, top, tag, script_name, library=str(lib), map_out=WORK)
    ports = clocks(netlist.read_text(), sequential)
    report = sta(script(netlist, lib, top, ports), WORK / f"{design}_{tag}_{script_name}.sta.log")
    return dict(design=design, library=tag, script=script_name, clocks=" ".join(ports), **worst(report))


def main(argv: list[str]):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--libraries", nargs="+", default=["reduced", "extended"], choices=list(LIBRARIES))
    args = parser.parse_args(argv)
    missing = [t for t in args.libraries if not LIBRARIES[t].exists()]
    if missing:
        raise SystemExit(f"no library for {missing}: run src.hd.liberty_writer (with --real for real)")
    sequential = {name for name, (_, seq) in cell_areas(LIBRARIES["reduced"].read_text()).items() if seq}
    WORK.mkdir(parents=True, exist_ok=True)
    NETLIST_OUT.mkdir(parents=True, exist_ok=True)
    jobs = [(d, top, tag, s) for d, top in DESIGNS.items() for tag in args.libraries for s in "AB"]
    with ThreadPoolExecutor(4) as pool:
        rows = list(pool.map(lambda j: time_design(*j, sequential), jobs))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(OUT.read_text())


if __name__ == "__main__":
    main(sys.argv[1:])
