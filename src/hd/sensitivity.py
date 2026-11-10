"""The 30% experiment (option 2 handout, section 4, step 12): make one new cell 30% smaller in the
Liberty and remap. ABC sees only the numbers in the Liberty, so this shows how much the result
depends on the area estimate.

The cells are the final set (results/hd/final_set.json) if it exists, otherwise the Liberty file's
default cells; the cell made smaller is the first of them (the one chosen first), or --cell. Every
required design is mapped with scripts A and B onto the reduced library, the library with the new
cells, and the same library with that one cell's area times FACTOR.

    python -m src.hd.sensitivity [--cell <name>] [--real]
        -> results/hd/sensitivity_30.csv, results/hd/sensitivity_30.txt
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from concurrent.futures import ThreadPoolExecutor

from src.hd.liberty_writer import REDUCED, extend, groups
from src.hd.request_writer import FINAL_SET, final_set, selected
from src.map_library.table1 import DESIGNS, LIBS, map_design
from src.paths import ROOT

FACTOR = 0.7        # section 4, step 12: 30% smaller
WORK = ROOT / "build/sensitivity"
OUT = ROOT / "results/hd"


def instances(log: str, cell: str) -> int:
    """How many times a cell is used, from a Yosys stat log."""
    return sum(int(n) for name, n in re.findall(r"^\s+(\S+)\s+(\d+)\s*$", log, re.M) if name == cell)


def libraries(cells: list[dict], cell: str, real: dict[str, str]) -> dict[str, str]:
    """The three libraries mapped: tag -> path."""
    library = REDUCED.read_text()
    WORK.mkdir(parents=True, exist_ok=True)
    paths = {"reduced": str(ROOT / LIBS["reduced"])}
    for tag, scale in (("extended", {}), ("scaled", {cell: FACTOR})):
        path = WORK / f"{tag}.lib"
        path.write_text(extend(library, groups(cells, library, scale, real)))
        paths[tag] = str(path)
    return paths


def main(argv: list[str]):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cell", help="the cell made smaller (default: the first of the set)")
    parser.add_argument("--real", action="store_true", help="use Option 1's real cells where they were accepted")
    args = parser.parse_args(argv)
    cells = selected(names=final_set()) if FINAL_SET.exists() else selected()
    cell = args.cell or cells[0]["name"]
    if cell not in {c["name"] for c in cells}:
        raise SystemExit(f"{cell} is not one of the cells: {[c['name'] for c in cells]}")
    real = {}
    if args.real:
        from src.hd.real_cells import intake
        real = {c["name"]: r.group for c in cells if (r := intake(c)).group}
    libs = libraries(cells, cell, real)

    jobs = [(d, top, tag, s) for d, top in DESIGNS.items() for tag in libs for s in "AB"]

    def job(j):
        design, top, tag, script = j
        area, _ = map_design(design, top, f"sens_{tag}", script, library=libs[tag], map_out=WORK)
        log = (WORK / f"{design}_sens_{tag}_{script}.log").read_text()
        return area, instances(log, cell)

    with ThreadPoolExecutor(4) as pool:
        results = dict(zip(jobs, pool.map(job, jobs)))

    def area(design, tag, script):
        if script == "best":                        # the smaller of the two scripts (section 7)
            return min(area(design, tag, s) for s in "AB")
        return results[(design, DESIGNS[design], tag, script)][0]

    def uses(design, tag, script):
        return "" if script == "best" else results[(design, DESIGNS[design], tag, script)][1]

    rows = []
    for design in DESIGNS:
        for script in ("A", "B", "best"):
            rows.append(dict(design=design, script=script, baseline_um2=area(design, "reduced", script),
                             extended_um2=area(design, "extended", script), scaled_um2=area(design, "scaled", script),
                             cell_instances=uses(design, "extended", script),
                             cell_instances_scaled=uses(design, "scaled", script)))
    total = {k: round(sum(r[k] for r in rows if r["script"] == "best"), 4)
             for k in ("baseline_um2", "extended_um2", "scaled_um2")}
    rows.append(dict(design="total", script="best", **total, cell_instances="", cell_instances_scaled=""))

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "sensitivity_30.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    def change(before, after):
        return f"{100 * (before - after) / before:+.2f}%"

    text = (f"30% experiment: {cell} area x {FACTOR} ({'real' if cell in real else 'estimated'} area), "
            f"{len(cells)} new cells, required designs, best of scripts A and B\n"
            f"baseline {total['baseline_um2']} um2\n"
            f"with the new cells {total['extended_um2']} um2 (reduction {change(total['baseline_um2'], total['extended_um2'])})\n"
            f"with {cell} 30% smaller {total['scaled_um2']} um2 "
            f"(reduction {change(total['baseline_um2'], total['scaled_um2'])})\n"
            f"{cell} used {sum(r['cell_instances'] for r in rows if r['script'] in ('A', 'B'))} times before, "
            f"{sum(r['cell_instances_scaled'] for r in rows if r['script'] in ('A', 'B'))} times after "
            f"(all designs, both scripts)\n")
    (OUT / "sensitivity_30.txt").write_text(text)
    print(text)


if __name__ == "__main__":
    main(sys.argv[1:])
