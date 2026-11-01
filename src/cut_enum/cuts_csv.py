"""Write the cut handoff file: one row per (design, AIG kind, leaf count, truth table).

    python -m src.cut_enum.cuts_csv [design ...]  -> results/cuts/<design>.csv

Reads build/aigs/<design>_{raw,abc}.aig (written by python -m src.aig.aigs).

Columns
    design, aig      design name; raw = straight from Yosys, abc = after strash; dch; strash
    n_leaves         2, 3 or 4 (the trivial cut of a node and 1-leaf cuts are skipped)
    tt_hex           truth table over n_leaves inputs, 2**n_leaves bits, written with 2**n_leaves/4
                     hex digits (at least 1). Bit i is the root value when leaf j equals bit j of i.
                     Leaves are sorted by node number, so "A" is the lowest-numbered leaf. The leaf
                     order is arbitrary, so M2 must classify up to input permutation.
    roots            number of distinct AIG nodes that have a cut with this table
    max_cone         maximum number of AND nodes between a root and its leaves, counted once per cut.
                     This is what the cut would replace, as a count of AIG nodes, not of mapped cells.

Counts are exact for the AIG; they are not the saving of a new cell, because cuts overlap.
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.cut_enum.cut_enumerator import CutEnumerator

ROOT = Path(__file__).resolve().parents[2]
AIGS = ROOT / "build/aigs"
OUT = ROOT / "results/cuts"
COLUMNS = ["design", "aig", "roots", "n_leaves", "tt_hex", "max_cone"]


def cone_size(ands: dict, root: int, leaves: tuple[int, ...]) -> int:
    """AND nodes on the way from root down to the leaves, shared nodes counted once."""
    stop, seen, stack = set(leaves), set(), [root]
    while stack:
        v = stack.pop()
        if v in stop or v in seen or v not in ands:
            continue
        seen.add(v)
        l_v, _, r_v, _ = ands[v]
        stack += [l_v, r_v]
    return len(seen)


def hex_digits(n_leaves: int) -> int:
    return max(1, (1 << n_leaves) // 4)


def rows_for(path: Path, design: str, kind: str, k: int = 4) -> list[list]:
    enum = CutEnumerator(path)
    node_cuts = enum.enumerate_cuts(k)
    roots: dict = defaultdict(set)
    cuts: dict = defaultdict(int)
    cones: dict = defaultdict(list)
    for node, cs in node_cuts.items():
        if node not in enum.ands:
            continue
        for leaves, table in cs.items():
            if len(leaves) < 2:
                continue
            key = (len(leaves), table)
            roots[key].add(node)
            cuts[key] += 1
            cones[key].append(cone_size(enum.ands, node, leaves))
    out = []
    for key in sorted(cuts, key=lambda x: (x[0], -cuts[x], x[1])):
        n, table = key
        c = cones[key]
        out.append([design, kind, len(roots[key]), n, f"{table:0{hex_digits(n)}X}", max(c)])
    return out


def write(design: str, kinds=("raw", "abc")) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for kind in kinds:
        rows += rows_for(AIGS / f"{design}_{kind}.aig", design, kind)
    path = OUT / f"{design}.csv"
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        w.writerows(rows)
    return path


def main(argv):
    from src.table1.table1 import DESIGNS
    for d in argv or list(DESIGNS):
        print(write(d))


if __name__ == "__main__":
    main(sys.argv[1:])