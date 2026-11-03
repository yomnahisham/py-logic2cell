"""Map designs with the reduced and extended libraries and write Table 5.

    python -m src.map_library.table5
        -> results/table5.csv
        -> build/equiv/<design>_<library>_<script>.{log,v}

The equivalence result is produced by ABC's ``cec`` script through Yosys.
The mapped cells are flattened using their Liberty functions before CEC
compares the two sequential designs.
"""

from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.common.yosys import ROOT, run
from src.map_library.map_extended import EXTENDED, count_new_cell_instances
from src.map_library.table1 import DESIGNS, LIBS, SCRIPTS, check_log

OUT = ROOT / "results/table5.csv"
WORK = ROOT / "build/equiv"
COLUMNS = [
    "design",
    "script",
    "baseline_um2",
    "new_cells_um2",
    "reduction_percent",
    "new_cell_instances",
    "equivalence",
]


def session(
    design: str,
    top: str,
    library: str,
    script: str,
    stem: Path,
    tamper: str = "",
) -> str:
    """Return one Yosys script that maps, records statistics, and runs CEC."""
    return "; ".join([
        f"read_verilog {design}",
        f"synth -flatten -top {top}",
        "design -save gold0",
        f"dfflibmap -liberty {library}",
        f'abc -liberty {library} -script "{SCRIPTS[script]}"',
        "opt_clean -purge",
        *([tamper] if tamper else []),
        f"tee -o {stem}.log stat -liberty {library}",
        f"write_verilog -noattr {stem}.v",
        "design -save gate0",
        "design -load gold0",
        f"read_liberty -ignore_miss_func {library}",
        f"hierarchy -top {top}",
        "flatten",
        "opt_clean",
        "design -save gold1",
        "design -load gate0",
        f"read_liberty -ignore_miss_func {library}",
        f"hierarchy -top {top}",
        "flatten",
        "opt_clean",
        "design -save gate1",
        "design -reset",
        f"design -copy-from gold1 -as gold {top}",
        f"design -copy-from gate1 -as gate {top}",
        "miter -equiv -flatten -ignore_gold_x gold gate miter",
        "hierarchy -top miter",
        "flatten",
        'abc -script "+cec"',
    ])


def verdict(output: str) -> bool:
    """Return whether ABC CEC proved the two designs equivalent."""
    return "Networks are equivalent" in output


def check(
    design: str,
    top: str,
    library: str,
    script: str,
    stem: Path,
    tamper: str = "",
) -> dict:
    """Map one design and return its area, generated-cell count, and CEC result."""
    # print(f"Mapping {design} with {library} using script {script}")
    stem.parent.mkdir(parents=True, exist_ok=True)
    output = run(["yosys", "-p", session(design, top, library, script, stem, tamper)])
    log = Path(f"{stem}.log").read_text()
    area, cells = check_log(log, f"{stem.name}.log")
    return {
        "equivalent": verdict(output),
        "area_um2": area,
        "cells": cells,
        "new_cell_instances": count_new_cell_instances(log),
    }


def libraries() -> dict[str, str]:
    """Return the baseline and generated libraries used for Table 5."""
    return {"reduced": LIBS["reduced"], "extended": str(EXTENDED)}


def _job(job: tuple[str, str, str, str, str]) -> tuple[dict, dict]:
    design, top, script, name, library = job
    stem = WORK / f"{design}_{name}_{script}"
    return (
        check(f"given/designs/{design}.v", top, library, script, stem),
        {"design": design, "script": script, "library": name},
    )


def main() -> None:
    if not EXTENDED.is_file():
        raise FileNotFoundError(f"{EXTENDED}: run `python -m src.hd.liberty_writer` first")

    jobs = [
        (design, top, script, name, library)
        for design, top in DESIGNS.items()
        for script in "AB"
        for name, library in libraries().items()
    ]
    with ThreadPoolExecutor(4) as pool:
        checked = list(pool.map(_job, jobs))

    by_key = {
        (meta["design"], meta["script"], meta["library"]): result
        for result, meta in checked
    }
    rows = []
    failures = []
    for design, top in DESIGNS.items():
        for script in "AB":
            baseline = by_key[(design, script, "reduced")]
            extended = by_key[(design, script, "extended")]
            reduction = 100.0 * (baseline["area_um2"] - extended["area_um2"]) / baseline["area_um2"]
            equivalent = baseline["equivalent"] and extended["equivalent"]
            rows.append([
                design,
                script,
                f"{baseline['area_um2']:.4f}",
                f"{extended['area_um2']:.4f}",
                f"{reduction:.2f}",
                extended["new_cell_instances"],
                "pass" if equivalent else "FAIL",
            ])
            if not equivalent:
                failures.append((design, script))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
    print(OUT.read_text())
    if failures:
        raise SystemExit(f"NOT EQUIVALENT: {failures}")


if __name__ == "__main__":
    main()
