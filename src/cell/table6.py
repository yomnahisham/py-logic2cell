"""Table 6 cells against the installed HD cells (Option 1 handout, section 6): width and area.

    python -m src.cell.table6          -> results/table6_vs_hd.csv

Run after the cells are built (build/cells/<name>/ must hold their GDS and extraction). The five
Table 6 functions that are also reference cells (section 4.1) are compared as built with --hd.
Delay and slew at the HD table point nearest 100 ps and 10 fF need the characterizer (section 5)
and are not in this table yet.
"""

from __future__ import annotations

import csv
from pathlib import Path

from src.cell import compare
from src.cell.layout import HEIGHT, SITE

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results/table6_vs_hd.csv"

# (our cell, installed HD cell, function as in Table 6)
PAIRS = [
    ("nand2_1", "nand2_1", "!(A & B)"),
    ("nor2_1", "nor2_1", "!(A | B)"),
    ("nand3_1", "nand3_1", "!(A & B & C)"),
    ("nor3_1", "nor3_1", "!(A | B | C)"),
    ("a21oi_1", "a21oi_1", "!((A & B) | C)"),
    ("o21ai_1", "o21ai_1", "!((A | B) & C)"),
    ("a22oi_1", "a22oi_1", "!((A & B) | (C & D))"),
    ("o22ai_1", "o22ai_1", "!((A | B) & (C | D))"),
    ("and2_1", "and2_1", "A & B"),
    ("a21o_1", "a21o_1", "(A & B) | C"),
    ("mux2_1", "mux2_1", "(A & !C) | (B & C)"),
    ("maj3_1", "maj3_1", "(A & B) | (C & (A | B))"),
    ("xor2_1", "xor2_1", "A ^ B"),
]


def rows() -> list[dict]:
    out = []
    for name, short, function in PAIRS:
        folder = ROOT / "build/cells" / f"dd2_gc1__{name}"
        r = compare.compare(folder, folder.name, short)
        ours, hd = r["width_sites"]["ours"], r["width_sites"]["hd"]
        out.append(dict(
            function=function, cell=folder.name, hd=compare.PREFIX + short,
            sites_ours=ours, sites_hd=hd, extra_sites=ours - hd,
            area_ours_um2=round(ours * SITE * HEIGHT, 4), area_hd_um2=round(hd * SITE * HEIGHT, 4),
            frame="match" if r["frame"]["match"] else "differs", lvs_vs_hd=r["lvs_vs_hd"],
            met1_inside="no" if r["wiring"]["ours"]["met1_only_rails"] else "yes",
            breaks_ours=sum(r["gates"]["ours"]["diffusion_breaks"].values()),
            breaks_hd=sum(r["gates"]["hd"]["diffusion_breaks"].values()),
            delay_slew="needs the characterizer"))
    return out


if __name__ == "__main__":
    table = rows()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(table[0]))
        w.writeheader()
        w.writerows(table)
    for row in table:
        print(f"{row['cell']:24s} {row['sites_ours']:>2} sites vs {row['sites_hd']:>2}  "
              f"area {row['area_ours_um2']:>7} vs {row['area_hd_um2']:>7} um2  lvs vs HD {row['lvs_vs_hd']:5s}  "
              f"met1 inside {row['met1_inside']:3s}  breaks {row['breaks_ours']} vs {row['breaks_hd']}")
    print(f"-> {OUT}")
