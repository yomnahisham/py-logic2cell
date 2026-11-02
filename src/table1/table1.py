"""Reproduce Table 1 and save the complete mapping logs used by later steps.

    python -m src.table1.table1
        -> results/table1.csv
        -> results/map/<design>_<usable|reduced>_<A|B>.log
"""

from __future__ import annotations

import csv
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.common.yosys import ROOT, run

DESIGNS = {"cpu8": "cpu8", "dsp8": "dsp8", "arlet6502": "cpu", "uart_apb": "uart_apb_master",
           "risc8": "cpu", "fir10": "fir10"}
LIBS = {"usable": "given/hd_usable.lib", "reduced": "given/hd_reduced.lib"}
OUT = ROOT / "results/table1.csv"
MAP_OUT = ROOT / "results/map"
SCRIPTS = {"A": "+strash;dch,-f;amap;topo", "B": "+strash;&get,-n;&dch,-f;&nf,-R,1000;&put"}


def check_log(text: str, name: str = "log") -> tuple[float, int]:
    """Validate and summarize a complete ``stat -liberty`` log."""
    area = re.findall(r"Chip area for module .*?:\s*([\d.]+)", text)
    cells = re.findall(r"Number of cells:\s*(\d+)", text)
    if not area or not cells:
        raise ValueError(f"{name}: no chip area or cell count in the stat output")
    counts = [int(c) for c in re.findall(r"^\s+\S+\s+(\d+)\s*$", text, re.M)]
    if sum(counts) != int(cells[-1]):
        raise ValueError(f"{name}: per-cell counts add up to {sum(counts)}, the log says {cells[-1]} cells")
    return float(area[-1]), int(cells[-1])


def map_design(
    design: str,
    top: str,
    lib: str,
    script: str,
    *,
    library: str | None = None,
    map_out: Path | None = None,
) -> tuple[float, int]:
    """Run one baseline mapping and retain the full stat log for rank.py."""
    library = library or LIBS[lib]
    map_out = map_out or MAP_OUT
    log = map_out / f"{design}_{lib}_{script}.log"
    run(["yosys", "-q", "-p",
         f"read_verilog given/designs/{design}.v; synth -flatten -top {top}; dfflibmap -liberty {library}; "
         f'abc -liberty {library} -script "{SCRIPTS[script]}"; opt_clean -purge; '
         f"tee -o {log} stat -liberty {library}"])
    return check_log(log.read_text(), log.name)


def main():
    jobs = [(d, t, lib, s) for d, t in DESIGNS.items() for s in "AB" for lib in LIBS]
    MAP_OUT.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda j: map_design(*j), jobs))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["design", "script", "library", "area_um2", "cells"])
        for (d, _, lib, s), (a, n) in zip(jobs, results):
            w.writerow([d, s, lib, f"{a:.4f}", n])
    print(OUT.read_text())


if __name__ == "__main__":
    main()
