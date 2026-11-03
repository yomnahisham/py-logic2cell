"""Classes of the cut truth tables (option 2 handout, section 4, step 3).

Reads the cut files of the cut enumerator, one row per non-trivial cut:

    design,aig,root,leaves,truth_table,cone_size

truth_table has 2**len(leaves) bits (bit i: leaf j equals bit j of i), and cone_size is the
number of AND nodes the cut covers, root included. Each table is first reduced to the inputs
it depends on; constants, buffers and inverters are dropped. Two tables are in the same class
when they are equal up to input order and output inversion (the class key is the smaller of
the P-canonical forms of t and !t). NPN classes, which also treat input inverters as free,
are counted for comparison only.

An occurrence is one root node: a node with several cuts in the same class counts once, with
its smallest cone.

    python -m src.hd.cut_classes [cut files]   -> results/hd/cut_classes.csv
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import csv
import glob
import sys
from functools import lru_cache

from src.hd.classes import canonical_truth_table
from src.paths import ROOT

CUTS = ROOT / "results/cuts"
SIZES = ROOT / "results/aig_sizes.csv"
OUT = ROOT / "results/hd/cut_classes.csv"


def reduce_support(table: int, n: int) -> tuple[int, int]:
    """The table over only the inputs it depends on, kept in their order; and how many."""
    used = [k for k in range(n)
            if any((table >> i & 1) != (table >> (i ^ 1 << k) & 1) for i in range(1 << n))]
    reduced = 0
    for j in range(1 << len(used)):
        i = sum((j >> pos & 1) << k for pos, k in enumerate(used))
        reduced |= (table >> i & 1) << j
    return reduced, len(used)


def invert(table: int, n: int) -> int:
    return table ^ ((1 << (1 << n)) - 1)


@lru_cache(maxsize=None)
def p_class(table: int, n: int) -> int:
    return canonical_truth_table(table, n)


@lru_cache(maxsize=None)
def pn_class(table: int, n: int) -> int:
    """Class up to input order and output inversion."""
    return min(p_class(table, n), p_class(invert(table, n), n))


@lru_cache(maxsize=None)
def npn_class(table: int, n: int) -> int:
    """Class up to input order, input inversion and output inversion."""
    best = None
    for mask in range(1 << n):
        flipped = sum((table >> (i ^ mask) & 1) << i for i in range(1 << n))
        c = pn_class(flipped, n)
        best = c if best is None else min(best, c)
    return best


def class_id(table: int, n: int) -> str:
    return f"c{n}_{table:0{max(1, (1 << n) // 4)}x}"


@dataclass
class Occurrences:
    """One class in one AIG: its root nodes, with the smallest cone and P-class of each."""
    roots: dict[int, tuple[int, int]] = field(default_factory=dict)  # root -> (cone, p-class table)

    def add(self, root: int, cone: int, p: int):
        if root not in self.roots or cone < self.roots[root][0]:
            self.roots[root] = (cone, p)

    @property
    def count(self) -> int:
        return len(self.roots)

    @property
    def cone_total(self) -> int:
        return sum(cone for cone, _ in self.roots.values())

    def polarity_counts(self) -> dict[int, int]:
        counts = defaultdict(int)
        for _, p in self.roots.values():
            counts[p] += 1
        return dict(counts)


@dataclass
class AigCuts:
    cuts: int = 0                       # non-trivial cuts read
    dropped: int = 0                    # constants, buffers and inverters after reduction
    classes: dict[tuple[int, int], Occurrences] = field(default_factory=lambda: defaultdict(Occurrences))


def read(paths) -> dict[tuple[str, str], AigCuts]:
    """(design, aig) -> its cuts grouped by class (key: (support size, class table))."""
    out: dict[tuple[str, str], AigCuts] = defaultdict(AigCuts)
    for path in paths:
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                aig = out[(row["design"], row["aig"])]
                aig.cuts += 1
                table, n = reduce_support(int(row["truth_table"], 16), len(row["leaves"].split()))
                if n < 2:
                    aig.dropped += 1
                    continue
                aig.classes[(n, pn_class(table, n))].add(int(row["root"]), int(row["cone_size"]),
                                                         p_class(table, n))
    return out


def aig_sizes(path=SIZES) -> dict[tuple[str, str], int]:
    """AND nodes of each design's AIGs, from the AIG export's results/aig_sizes.csv."""
    if not path.exists():
        return {}
    with path.open() as f:
        return {(r["design"], aig): int(r[f"ands_{aig}"]) for r in csv.DictReader(f) for aig in ("raw", "abc")}


def summary(aigs: dict[tuple[str, str], AigCuts]) -> list[dict]:
    """One row per design and AIG, then one row per AIG for all designs together."""
    sizes = aig_sizes()

    def row(design, aig, cuts, dropped, keys):
        return dict(design=design, aig=aig, ands=sizes.get((design, aig), ""), cuts=cuts, dropped=dropped,
                    classes=len(keys), classes_4=sum(n == 4 for n, _ in keys),
                    npn_classes=len({(n, npn_class(t, n)) for n, t in keys}),
                    npn_classes_4=len({npn_class(t, n) for n, t in keys if n == 4}))

    rows = [row(design, aig, a.cuts, a.dropped, set(a.classes)) for (design, aig), a in sorted(aigs.items())]
    for aig in sorted({aig for _, aig in aigs}):
        mine = [a for (_, g), a in aigs.items() if g == aig]
        rows.append(row("all", aig, sum(a.cuts for a in mine), sum(a.dropped for a in mine),
                        set().union(*(a.classes for a in mine))))
    return rows


def cut_files(args: list[str]) -> list[str]:
    return sorted(args or glob.glob(str(CUTS / "*.csv")))


def main(args: list[str]):
    rows = summary(read(cut_files(args)))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(OUT.read_text())


if __name__ == "__main__":
    main(sys.argv[1:])
