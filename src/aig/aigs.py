"""Write the AIG of every required design, before and after ABC restructuring (option 2 handout, step 1).

Raw: Yosys 0.33, synth -flatten, async2sync + dffunmap, aigmap, write_aiger -zinit.
ABC: yosys-abc on the raw AIG with strash; dch; strash (the last strash drops the choice nodes dch adds).

    python -m src.aig.aigs          -> build/aigs/<design>_{raw,abc}.{aig,aag}, results/aig_sizes.csv
"""

from __future__ import annotations

import csv
import re
from concurrent.futures import ThreadPoolExecutor

from src.aig import aiger
from src.common.yosys import ROOT, run
from src.table1.table1 import DESIGNS

OUT = ROOT / "build/aigs"
SIZES = ROOT / "results/aig_sizes.csv"


def header(path) -> dict:
    m, i, l, o, a = map(int, path.read_text().split("\n", 1)[0].split()[1:6])
    return dict(inputs=i, latches=l, outputs=o, ands=a)


def write(design: str, top: str) -> dict:
    raw, abc = OUT / f"{design}_raw", OUT / f"{design}_abc"
    run(["yosys", "-q", "-p",
         f"read_verilog given/designs/{design}.v; synth -flatten -top {top}; async2sync; dffunmap; aigmap; "
         f"write_aiger -zinit {raw}.aig; write_aiger -zinit -ascii {raw}.aag"])
    run(["yosys-abc", "-q", f"read {raw}.aig; strash; dch; strash; write_aiger {abc}.aig"])
    aiger.write_aag(aiger.read(f"{abc}.aig"), f"{abc}.aag")
    return dict(design=design, raw=header(raw.with_suffix(".aag")), abc=header(abc.with_suffix(".aag")))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(4) as pool:
        rows = list(pool.map(lambda d: write(d, DESIGNS[d]), DESIGNS))
    SIZES.parent.mkdir(parents=True, exist_ok=True)
    with SIZES.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["design", "inputs", "outputs", "latches", "ands_raw", "ands_abc"])
        for r in rows:
            w.writerow([r["design"], r["raw"]["inputs"], r["raw"]["outputs"], r["raw"]["latches"],
                        r["raw"]["ands"], r["abc"]["ands"]])
    print(SIZES.read_text())


if __name__ == "__main__":
    main()
