"""Reproduce Table 1 of the option 2 handout: area of each required design on the
usable and reduced HD libraries, with scripts A and B, using given/scripts/map.sh.

    python -m src.table1.table1          -> results/table1.csv
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


def area(design: str, top: str, lib: str, script: str) -> tuple[float, int]:
    out = run(["sh", "given/scripts/map.sh", f"given/designs/{design}.v", top, lib, script])
    return float(re.search(r"Chip area for module .*?:\s*([\d.]+)", out)[1]), int(re.search(r"Number of cells:\s*(\d+)", out)[1])


def main():
    jobs = [(d, t, lib, s) for d, t in DESIGNS.items() for s in "AB" for lib in LIBS]
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda j: area(j[0], j[1], LIBS[j[2]], j[3]), jobs))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["design", "script", "library", "area_um2", "cells"])
        for (d, _, lib, s), (a, n) in zip(jobs, results):
            w.writerow([d, s, lib, f"{a:.4f}", n])
    print(OUT.read_text())


if __name__ == "__main__":
    main()
