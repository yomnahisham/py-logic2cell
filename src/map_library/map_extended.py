"""Map the required designs with the generated extended reduced library.

    python -m src.map_library.map_extended
        -> results/table1_extended.csv
        -> results/map_extended/<design>_extended_<A|B>.log
"""

from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor

from src.common.yosys import ROOT
from src.map_library.table1 import DESIGNS, map_design

EXTENDED = ROOT / "build/libs/hd_reduced_ext.lib"
OUT = ROOT / "results/table1_extended.csv"
MAP_EXTENDED_OUT = ROOT / "results/map_extended"


def main() -> None:
    """Map every required design with both standard ABC scripts."""
    if not EXTENDED.is_file():
        raise FileNotFoundError(
            f"{EXTENDED}: run `python -m src.hd.liberty_writer` first")

    jobs = [(design, top, script) for design, top in DESIGNS.items() for script in "AB"]
    MAP_EXTENDED_OUT.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(
            lambda job: map_design(
                job[0],
                job[1],
                "extended",
                job[2],
                library=str(EXTENDED),
                map_out=MAP_EXTENDED_OUT,
            ),
            jobs,
        ))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(["design", "script", "library", "area_um2", "cells"])
        for (design, _, script), (area, cells) in zip(jobs, results):
            writer.writerow([design, script, "extended", f"{area:.4f}", cells])
    print(OUT.read_text())


if __name__ == "__main__":
    main()