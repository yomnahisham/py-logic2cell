"""The greedy selection of the final set (option 2 handout, section 4, step 10).

Add the best remaining candidate (candidates are tried in the order of the ranking), remap the
required designs with the reduced library plus the cells kept so far plus that candidate, and keep
it only if the total area drops. Stop after LIMIT (10) cells or when no candidate helps.

The area is the total over the six required designs of the smaller of scripts A and B (section 7),
because that is the area a designer would get. Candidates are the ones Option 1's structure can
build and that have a positive estimated saving, the first --pool of them. Areas are the estimated
ones; the real cells replace them afterwards (step 11).

    python -m src.hd.greedy [--pool 30] [--limit 10] [--retry]
        -> results/hd/final_set.json, results/hd/greedy.csv, results/hd/greedy.txt

--retry: after a pass, go through the rejected candidates again, since a cell that did not help
alone can help once others are in. A mapping that fails (Yosys or ABC error) counts as a rejection
and is logged.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from typing import Callable

from src.hd.request_writer import FINAL_SET, LIMIT, candidates
from src.paths import ROOT

OUT = ROOT / "results/hd"
TOLERANCE = 1e-4        # um2: a smaller total than this is noise, not a saving


def pool_of(ranked: list[dict], size: int) -> list[dict]:
    """The candidates to try, in rank order."""
    return [c for c in ranked if c.get("buildable", True) and c["saving_um2"]["total"] > 0][:size]


def greedy(pool: list[dict], trial: Callable[[list[dict]], dict], limit: int = LIMIT,
           retry: bool = False, log: Callable[[str], None] = print) -> tuple[list[dict], list[dict], dict]:
    """trial(cells) -> {"total": um2, ...}. Returns the chosen cells in order, the trace (one row
    per trial) and the baseline measurement."""
    baseline = current = trial([])
    chosen: list[dict] = []
    trace: list[dict] = []
    remaining = list(pool)
    while remaining and len(chosen) < limit:
        rejected, added = [], False
        for cand in remaining:
            if len(chosen) >= limit: 
                rejected.append(cand)
                continue
            row = {"step": len(trace) + 1, "candidate": cand["name"], "estimated_um2": cand["area_um2"],
                   "total_before": current["total"], "total_after": "", "decision": ""}
            try:
                result = trial(chosen + [cand])
            except (RuntimeError, ValueError) as error:
                row["decision"] = f"error: {str(error).splitlines()[0][:80]}"
                rejected.append(cand)
            else:
                row["total_after"] = result["total"]
                if result["total"] < current["total"] - TOLERANCE:
                    row["decision"] = "kept"
                    chosen.append(cand)
                    current, added = result, True
                else:
                    row["decision"] = "rejected"
                    rejected.append(cand)
            trace.append(row)
            log(f"{row['step']:3} {cand['name']}: {row['total_before']} -> {row['total_after']} {row['decision']}")
        remaining = rejected
        if not (retry and added):
            break
    return chosen, trace, baseline if not chosen else {**current, "baseline_total": baseline["total"]}


def main(argv: list[str]):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--pool", type=int, default=30, help="how many ranked candidates to try")
    parser.add_argument("--limit", type=int, default=LIMIT, help="at most this many new cells")
    parser.add_argument("--retry", action="store_true", help="retry rejected candidates after each pass")
    args = parser.parse_args(argv)
    from src.hd.measure import measure          # needs Yosys; imported here so tests need not

    pool = pool_of(candidates(), args.pool)
    count = [0]

    def trial(cells):
        count[0] += 1
        return measure(cells, tag="greedy")

    chosen, trace, final = greedy(pool, trial, args.limit, args.retry)
    base = final.get("baseline_total", final["total"])
    OUT.mkdir(parents=True, exist_ok=True)
    FINAL_SET.write_text(json.dumps({"cells": [c["name"] for c in chosen], "baseline_um2": base,
                                     "total_um2": final["total"], "metric": "sum over the required designs "
                                     "of the smaller of scripts A and B"}, indent=2) + "\n")
    with (OUT / "greedy.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(trace[0]) if trace else ["step"])
        w.writeheader()
        w.writerows(trace)
    saving = 100 * (base - final["total"]) / base
    text = (f"greedy selection: {len(pool)} candidates in the pool, {len(trace)} trials, "
            f"{len(chosen)} cells kept (limit {args.limit}{', retry' if args.retry else ''})\n"
            f"baseline {base} um2 -> {final['total']} um2 (estimated areas, best of both, required designs): "
            f"{saving:+.2f}% reduction\n" + "".join(f"  {i}. {c['name']}\n" for i, c in enumerate(chosen, 1)))
    (OUT / "greedy.txt").write_text(text)
    print(text)


if __name__ == "__main__":
    main(sys.argv[1:])