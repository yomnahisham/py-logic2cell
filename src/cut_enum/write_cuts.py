"""Write every non-trivial cut of every required design's AIGs to results/cuts/<design>_<aig>.csv
(option 2 handout, section 4, steps 2 and 3). src/hd/cut_classes.py reads these files.

    python -m src.cut_enum.write_cuts [--no-check] [design ...]   -> results/cuts/<design>_{raw,abc}.csv
    columns: design,aig,root,leaves,truth_table,cone_size

Every cut's table is checked against simulation before it is written; a disagreement stops the run.
"""

from __future__ import annotations

import csv
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from src.cut_enum.cut_enumerator import CutEnumerator
from src.paths import ROOT
from src.map_library.table1 import DESIGNS

AIGS = ROOT / "build/aigs"
OUT = ROOT / "results/cuts"
COLUMNS = ["design", "aig", "root", "leaves", "truth_table", "cone_size"]


def cone_size(ands: dict, root: int, leaves: tuple[int, ...]) -> int:
    """AND nodes between the leaves and the root, root included."""
    stop, seen, stack = set(leaves), set(), [root]
    while stack:
        v = stack.pop()
        if v in seen or v in stop or v not in ands:
            continue
        seen.add(v)
        l_v, _, r_v, _ = ands[v]
        stack += [l_v, r_v]
    return len(seen)


def write(design: str, aig: str, src: Path = AIGS, out: Path = OUT, check: bool = True) -> int:
    """Write one design's cut file for one AIG kind (raw or abc). Returns the number of cuts."""
    for suffix in (".aig", ".aag"):
        path = Path(src) / f"{design}_{aig}{suffix}"
        if path.exists():
            break
    else:
        raise FileNotFoundError(f"{src}/{design}_{aig}.aig: run python -m src.aig.aigs first")
    enum = CutEnumerator(path)
    node_cuts = enum.enumerate_cuts(4)
    if check:
        bad = enum.check(node_cuts)
        if bad:
            raise AssertionError(f"{design} {aig}: {len(bad)} cuts disagree with simulation, first {bad[0]}")
    Path(out).mkdir(parents=True, exist_ok=True)
    n = 0
    with (Path(out) / f"{design}_{aig}.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for root, cuts in node_cuts.items():
            if root not in enum.ands:
                continue
            for leaves, table in sorted(cuts.items()):
                if leaves == (root,):
                    continue
                digits = max(1, (1 << len(leaves)) // 4)
                w.writerow([design, aig, root, " ".join(map(str, leaves)), f"0x{table:0{digits}x}",
                            cone_size(enum.ands, root, leaves)])
                n += 1
    return n


def _job(args):
    design, aig, check = args
    return design, aig, write(design, aig, check=check)


def main(argv: list[str]):
    check = "--no-check" not in argv
    designs = [a for a in argv if not a.startswith("--")] or list(DESIGNS)
    jobs = [(d, a, check) for d in designs for a in ("raw", "abc")]
    with ProcessPoolExecutor() as pool:
        for design, aig, n in pool.map(_job, jobs):
            print(f"{design:10s} {aig:4s} {n:8d} cuts{' (checked)' if check else ''}")


if __name__ == "__main__":
    main(sys.argv[1:])