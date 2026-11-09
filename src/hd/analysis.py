"""Data for two questions of the report (option 2 handout, section 9.3):
  - do risc8, pic16 and p16c5x, which implement one instruction set, favour the same new cells?
  - a frequent function that did not save area, and why.

Per design: every design with a cut file (results/cuts/<design>_abc.csv) and a baseline stat log
(build/map/<design>_reduced_A.log) is ranked on its own (src.hd.rank.rank_rows), and its best cells
are listed. Frequency against saving: for each cell of the Liberty file, how often its class occurs,
its estimated saving, and how many instances the mappings with the new cells used
(build/map_extended/<design>_extended_<script>.log, where they exist).

    python -m src.hd.analysis [--top 10]
        -> results/hd/per_design.csv, results/hd/per_design.txt, results/hd/frequency_vs_saving.csv,
           results/hd/frequency_vs_saving.txt
"""

from __future__ import annotations

import argparse
import csv
import sys
from itertools import combinations

from src.hd.cut_classes import CUTS, read
from src.hd.rank import MAPS, REQUIRED, rank_rows, ranked, cell_name, stat
from src.hd.request_writer import selected
from src.paths import ROOT

ISA = ["risc8", "pic16", "p16c5x"]        # one instruction set (handout, section 9.3)
EXTENDED_MAPS = ROOT / "build/map_extended"
OUT = ROOT / "results/hd"


def available() -> list[str]:
    """Designs with an ABC cut file and a baseline stat log."""
    return sorted(p.name.removesuffix("_abc.csv") for p in CUTS.glob("*_abc.csv")
                  if (MAPS / f"{p.name.removesuffix('_abc.csv')}_reduced_A.log").exists())


def per_design(designs: list[str], top: int) -> dict[str, list[dict]]:
    """Each design's best `top` cells, ranked on that design alone."""
    out = {}
    for d in designs:
        rows, _, _ = rank_rows(read([CUTS / f"{d}_abc.csv"]), [d])
        out[d] = [dict(design=d, rank=i + 1, cell=cell_name(r["_table"], r["inputs"]), class_id=r["class_id"],
                       expression=r["_estimate"].expression, buildable=r["buildable"], occurrences=r["occurrences"],
                       saving_um2=r["saving_um2"]) for i, r in enumerate(ranked(rows)[:top])]
    return out


def overlap_text(best: dict[str, list[dict]]) -> list[str]:
    lines = ["", f"one instruction set ({', '.join(ISA)}):"]
    have = [d for d in ISA if d in best]
    missing = [d for d in ISA if d not in best]
    if missing:
        lines.append(f"  no cuts or baseline log yet for {', '.join(missing)}")
    sets = {d: {r["cell"] for r in best[d]} for d in have}
    for a, b in combinations(have, 2):
        shared = sets[a] & sets[b]
        lines.append(f"  {a} and {b}: {len(shared)} of their best {len(best[a])} cells shared: {', '.join(sorted(shared)) or '-'}")
    if len(have) > 2:
        common = set.intersection(*sets.values())
        lines.append(f"  in all three: {len(common)}: {', '.join(sorted(common)) or '-'}")
    return lines


def extended_instances(cell: str) -> dict[str, int]:
    """Instances of a cell per mapping with the new cells, keyed <design>_<script>."""
    out = {}
    for design in REQUIRED:
        for script in "AB":
            log = EXTENDED_MAPS / f"{design}_extended_{script}.log"
            if log.exists():
                out[f"{design}_{script}"] = stat(log)[1].get(cell, 0)
    return out


def frequency_vs_saving() -> tuple[list[dict], list[str]]:
    rows = []
    for c in selected():
        uses = extended_instances(c["name"])
        rows.append(dict(cell=c["name"], expression=c["expression"], occurrences=sum(c["occurrences"].values()),
                         estimated_saving_um2=c["saving_um2"]["total"], area_um2=c["area_um2"],
                         instances=sum(uses.values()) if uses else "",
                         **{f"instances_{k}": v for k, v in uses.items()}))
    rows.sort(key=lambda r: -r["occurrences"])
    lines = ["frequency against saving, the cells of the Liberty file, most frequent first:"]
    for r in rows:
        lines.append(f"  {r['cell']}: {r['occurrences']} occurrences, estimated saving {r['estimated_saving_um2']} um2, "
                     f"used {r['instances'] if r['instances'] != '' else '?'} times in the mappings")
    used = [r for r in rows if r["instances"] != ""]
    if used:
        r = max(used, key=lambda r: r["occurrences"] / (1 + r["instances"]))
        lines.append(f"most frequent for how little it was used: {r['cell']} ({r['expression']}), "
                     f"{r['occurrences']} occurrences, {r['instances']} instances")
    return rows, lines


def write_csv(path, rows):
    if rows:
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)


def main(argv: list[str]):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)

    best = per_design(available(), args.top)
    write_csv(OUT / "per_design.csv", [r for rows in best.values() for r in rows])
    lines = [f"best {args.top} cells of each design, ranked on that design alone:"]
    for d, rows in best.items():
        lines.append(f"  {d}: " + ", ".join(f"{r['cell']} ({r['saving_um2']})" for r in rows[:5])
                     + (" ..." if len(rows) > 5 else ""))
    lines += overlap_text(best)
    (OUT / "per_design.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))

    rows, lines = frequency_vs_saving()
    write_csv(OUT / "frequency_vs_saving.csv", rows)
    (OUT / "frequency_vs_saving.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1:])
