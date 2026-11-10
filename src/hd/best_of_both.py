"""Best-of-both reductions from Table 5 (option 2 handout, section 7).

Table 5 gives the same-script reduction. A designer would take the smaller of the two scripts on
each side, so here every design's baseline is min(A, B) of the reduced library and its new area is
min(A, B) of the library with the new cells. The last row is the total over the required designs.

    python -m src.hd.best_of_both [--real]
        -> results/table5_best.csv, results/table5_best.txt          (from results/table5.csv)
           results/table5_best_real.csv, ...                         (from results/table5_real.csv)
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from src.paths import ROOT

COLUMNS = ["design", "baseline_best_um2", "baseline_script", "new_best_um2", "new_script",
           "reduction_percent", "equivalence"]


def best_rows(table5: list[dict]) -> list[dict]:
    """table5: the rows of results/table5.csv. One row per design, then a 'total' row."""
    designs = list(dict.fromkeys(r["design"] for r in table5))
    rows = []
    for d in designs:
        mine = [r for r in table5 if r["design"] == d]
        base = min(mine, key=lambda r: float(r["baseline_um2"]))
        new = min(mine, key=lambda r: float(r["new_cells_um2"]))
        b, n = float(base["baseline_um2"]), float(new["new_cells_um2"])
        rows.append({"design": d, "baseline_best_um2": f"{b:.4f}", "baseline_script": base["script"],
                     "new_best_um2": f"{n:.4f}", "new_script": new["script"],
                     "reduction_percent": f"{100 * (b - n) / b:.2f}",
                     "equivalence": "pass" if all(r["equivalence"] == "pass" for r in mine) else "FAIL"})
    b = sum(float(r["baseline_best_um2"]) for r in rows)
    n = sum(float(r["new_best_um2"]) for r in rows)
    rows.append({"design": "total", "baseline_best_um2": f"{b:.4f}", "baseline_script": "",
                 "new_best_um2": f"{n:.4f}", "new_script": "", "reduction_percent": f"{100 * (b - n) / b:.2f}",
                 "equivalence": "pass" if all(r["equivalence"] == "pass" for r in rows) else "FAIL"})
    return rows


def write(src: Path, out_csv: Path) -> str:
    with src.open() as f:
        rows = best_rows(list(csv.DictReader(f)))
    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    text = "".join(f"{r['design']:10} {r['baseline_best_um2']:>12} -> {r['new_best_um2']:>12} um2  "
                   f"{r['reduction_percent']:>6}%  cec {r['equivalence']}\n" for r in rows)
    out_csv.with_suffix(".txt").write_text(text)
    return text


def main(argv: list[str]):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--real", action="store_true")
    args = parser.parse_args(argv)
    suffix = "_real" if args.real else ""
    print(write(ROOT / f"results/table5{suffix}.csv", ROOT / f"results/table5_best{suffix}.csv"))


if __name__ == "__main__":
    main(sys.argv[1:])