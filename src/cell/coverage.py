"""Which functions the generator can draw (option 1 handout, section 3.1: "any single-output Boolean function
of up to 4 inputs"): one function per NPN class of 4-input functions that depend on all four inputs, placed
only (no views, no checks), with its width or the reason it was refused.

    python -m src.cell.coverage [--limit N]      -> results/coverage.csv

A class stands for every function that permuting or inverting its inputs, or inverting its output, gives;
inverters at the inputs and output are the same stages for all of them, so a class drawn says that its
whole class can be built (the widths differ by those inverters). Placement only: a function placed here is
then built and checked as any other request.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

from src.cell import build as b
from src.hd.cut_classes import npn_class

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results/coverage.csv"
WORK = ROOT / "build/coverage"


def classes() -> list[int]:
    """The smallest truth table of each NPN class of 4-input functions that depend on every input."""
    full = lambda t: all(any((t >> i & 1) != (t >> (i ^ 1 << k) & 1) for i in range(16)) for k in range(4))
    return sorted({npn_class(t, 4) for t in range(1 << 16) if full(t)})


def expression(table: int) -> str:
    """A sum of products over A..D (input A is bit 0) for a request; the build finds its own network."""
    terms = [" & ".join(("" if i >> k & 1 else "!") + "ABCD"[k] for k in range(4)) for i in range(16) if table >> i & 1]
    return " | ".join(f"({t})" for t in terms) or "A & !A"


def main(limit: int | None):
    WORK.mkdir(parents=True, exist_ok=True)
    b.CELLS["handout"] = str((WORK / "cells").relative_to(ROOT))    # refusals go here, not in cells/
    rows = []
    for table in classes()[:limit]:
        name = f"dd2_gc1__cov_{table:04x}"
        req = WORK / f"{name}.json"
        req.write_text(json.dumps(dict(request_id=f"COV-{table:04X}", name=name, inputs=list("ABCD"), output="Y",
                                       expression=expression(table), truth_table=f"0x{table:04X}", sizing="hd")))
        t = time.time()
        r = b.build(req, place_only=True)
        rows.append(dict(class_table=f"0x{table:04X}", status=r["status"], stages=r.get("stages", ""),
                         transistors=r.get("transistors", ""), width_sites=r.get("width_sites", ""),
                         met1=r.get("met1", ""), seconds=round(time.time() - t), reason=r.get("reason") or ""))
        print(f"0x{table:04X} {r['status']:7s} {r.get('width_sites', '')} {round(time.time() - t)} s {(r.get('reason') or '')[:80]}", flush=True)
        with OUT.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    placed = sum(r["status"] == "placed" for r in rows)
    print(f"{placed} of {len(rows)} classes drawn -> {OUT}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    main(ap.parse_args().limit)
