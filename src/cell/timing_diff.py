"""Compare two characterizations of the same cell, entry by entry.

    python -m src.cell.timing_diff <a_timing.json> <b_timing.json>

Used to check that a change to the simulation settings (time step) leaves the numbers alone, and for the
stock against the fixed ngspice (option 1 handout, section 5.1, Simulator). Prints the largest and median
relative difference of b against a, per table and for the pin capacitances.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path


def diff(a: dict, b: dict) -> list[tuple[str, float]]:
    out = []
    for arc_a, arc_b in zip(a["arcs"], b["arcs"]):
        if (arc_a["pin"], arc_a["index_1"], arc_a["index_2"]) != (arc_b["pin"], arc_b["index_1"], arc_b["index_2"]):
            raise ValueError(f"the two runs differ in arcs or grids: {arc_a['pin']} vs {arc_b['pin']}")
        for name, rows in arc_a["tables"].items():
            for i, row in enumerate(rows):
                for j, va in enumerate(row):
                    vb = arc_b["tables"][name][i][j]
                    if va is not None and vb is not None:
                        out.append((f"{arc_a['pin']} {name} slew {arc_a['index_1'][i]} load {arc_a['index_2'][j]}",
                                    (vb - va) / va * 100))
    for pin, ca in a["pins"].items():
        for key in ("rise_capacitance", "fall_capacitance"):
            if ca.get(key) and b["pins"][pin].get(key):
                out.append((f"{pin} {key}", (b["pins"][pin][key] - ca[key]) / ca[key] * 100))
    return out


if __name__ == "__main__":
    a, b = (json.loads(Path(p).read_text()) for p in sys.argv[1:3])
    d = diff(a, b)
    worst = max(d, key=lambda x: abs(x[1]))
    print(f"{a['cell']}: {len(d)} values, b against a")
    print(f"  ngspice a {a['ngspice']['sha256'][:12]}  b {b['ngspice']['sha256'][:12]}")
    print(f"  median |diff| {statistics.median(abs(v) for _, v in d):.3f}%   largest {worst[1]:+.3f}% at {worst[0]}")
