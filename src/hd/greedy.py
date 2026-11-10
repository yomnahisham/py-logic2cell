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

--swap: after the greedy, a local search (1-exchange): replace one chosen cell by one rejected cell and
keep the swap if the total area drops, until no swap helps. It never ends worse than the greedy, and
it can find a set the greedy's fixed order misses. An exhaustive search is out of reach (sets of at
most 10 of 24 candidates: 4,540,386, each 12 mappings), and neither dynamic programming nor branch and
bound applies: the mapped area of a set is not a sum over its cells, since ABC covers each design as a
whole and one cell changes where another is used. Its result goes to final_set_swap.json and
greedy_swap.{csv,txt}; final_set.json stays the greedy's, as step 10 asks.
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


def swaps(chosen: list[dict], rejected: list[dict], current: dict, trial: Callable[[list[dict]], dict],
          passes: int = 3, log: Callable[[str], None] = print) -> tuple[list[dict], list[dict], dict]:
    """1-exchange local search from the greedy's set. Returns the set, the trace and its measurement."""
    chosen, rejected, trace = list(chosen), list(rejected), []
    for _ in range(passes):
        improved = False
        for i in range(len(chosen)):
            for j, cand in enumerate(rejected):
                trial_set = chosen[:i] + [cand] + chosen[i + 1:]
                row = {"step": len(trace) + 1, "out": chosen[i]["name"], "in": cand["name"],
                       "total_before": current["total"], "total_after": "", "decision": ""}
                try:
                    result = trial(trial_set)
                except (RuntimeError, ValueError) as error:
                    row["decision"] = f"error: {str(error).splitlines()[0][:80]}"
                else:
                    row["total_after"] = result["total"]
                    if result["total"] < current["total"] - TOLERANCE:
                        row["decision"] = "swapped"
                        rejected[j] = chosen[i]
                        chosen, current, improved = trial_set, result, True
                    else:
                        row["decision"] = "kept"
                trace.append(row)
                log(f"{row['step']:3} {row['out']} -> {row['in']}: {row['total_before']} -> {row['total_after']} {row['decision']}")
        if not improved:
            break
    return chosen, trace, current


def main(argv: list[str]):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--pool", type=int, default=30, help="how many ranked candidates to try")
    parser.add_argument("--limit", type=int, default=LIMIT, help="at most this many new cells")
    parser.add_argument("--retry", action="store_true", help="retry rejected candidates after each pass")
    parser.add_argument("--swap", action="store_true", help="then a swap search; written beside the greedy's set")
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
    if args.swap and chosen:
        rejected = [c for c in pool if c not in chosen]
        best, swap_trace, result = swaps(chosen, rejected, final, trial)
        (OUT / "final_set_swap.json").write_text(json.dumps({"cells": [c["name"] for c in best], "baseline_um2": base,
                                                            "total_um2": result["total"], "from": "greedy, then swaps"},
                                                           indent=2) + "\n")
        with (OUT / "greedy_swap.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(swap_trace[0]) if swap_trace else ["step"])
            w.writeheader()
            w.writerows(swap_trace)
        gain = 100 * (base - result["total"]) / base
        swap_text = (f"swap search after the greedy: {len(swap_trace)} trials, "
                     f"{sum(r['decision'] == 'swapped' for r in swap_trace)} swaps kept\n"
                     f"greedy {final['total']} um2 ({saving:+.2f}%) -> swaps {result['total']} um2 ({gain:+.2f}%), "
                     f"baseline {base} um2\n" + "".join(f"  {i}. {c['name']}\n" for i, c in enumerate(best, 1)))
        (OUT / "greedy_swap.txt").write_text(swap_text)
        print(swap_text)


if __name__ == "__main__":
    main(sys.argv[1:])