"""The cell-by-cell curve (option 2 handout, section 7): add the final cells one at a time, in the
order the greedy selection chose them, and record the total best-of-both area of the required
designs after each.

    python -m src.hd.curve [--real]
        -> results/hd/curve.csv, curve.txt, curve.png      (estimated areas)
           results/hd/curve_real.csv, ...                  (--real: Option 1's real cells where accepted)

The first row (step 0) is the baseline, the reduced library alone.
"""

from __future__ import annotations

import argparse
import csv
import sys

from src.hd.request_writer import FINAL_SET, final_set, selected
from src.paths import ROOT

OUT = ROOT / "results/hd"


def rows_of(cells: list[dict], trial) -> list[dict]:
    """One row per prefix of `cells`: trial(cells[:k]) -> {"total", "best"}."""
    rows, base = [], None
    for k in range(len(cells) + 1):
        result = trial(cells[:k])
        base = result["total"] if base is None else base
        rows.append({"step": k, "cell": cells[k - 1]["name"] if k else "(baseline)",
                     "total_best_um2": result["total"],
                     "change_um2": round(result["total"] - base, 4),
                     "reduction_percent": round(100 * (base - result["total"]) / base, 3),
                     **{f"{d}_um2": a for d, a in result["best"].items()}})
    return rows


def plot(rows: list[dict], path, title: str):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib is missing: no figure")
        return
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot([r["step"] for r in rows], [r["total_best_um2"] for r in rows], marker="o")
    ax.set_xticks([r["step"] for r in rows])
    ax.set_xticklabels([r["cell"].replace("dd2_gc1__", "") for r in rows], rotation=60, ha="right", fontsize=7)
    ax.set_ylabel("total area, best of A and B (um2)")
    ax.set_title(title)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def main(argv: list[str]):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--real", action="store_true", help="use Option 1's real cells where they were accepted")
    args = parser.parse_args(argv)
    from src.hd.measure import measure          # needs Yosys; imported here so tests need not

    cells = selected(names=final_set())
    real = {}
    if args.real:
        from src.hd.real_cells import intake
        for c in cells:
            r = intake(c)
            print(f"  {c['name']}: {'real' if r.group else 'estimated'} ({r.reason})")
            if r.group:
                real[c["name"]] = r.group
    suffix = "_real" if args.real else ""
    rows = rows_of(cells, lambda prefix: measure(prefix, real, tag=f"curve{suffix}_{len(prefix)}"))
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / f"curve{suffix}.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    kind = f"{len(real)} real cells, the rest estimated" if args.real else "estimated areas"
    text = f"cell-by-cell curve ({kind}), from {FINAL_SET.name}\n" + "".join(
        f"  {r['step']:2} {r['cell']}: {r['total_best_um2']} um2 ({r['reduction_percent']:+.3f}%)\n" for r in rows)
    (OUT / f"curve{suffix}.txt").write_text(text)
    plot(rows, OUT / f"curve{suffix}.png", f"Total area as the final cells are added ({kind})")
    print(text)


if __name__ == "__main__":
    main(sys.argv[1:])