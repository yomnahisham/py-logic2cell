"""Data for two questions of the report (option 2 handout, section 9.3):
  - do risc8, pic16 and p16c5x, which implement one instruction set, favour the same new cells?
  - a frequent function that did not save area, and why.

Per design: the required designs, and pic16 and p16c5x (their AIG, cuts and baseline mapping are made
here if missing, the cuts in build/analysis/cuts), are each ranked on their own
(src.hd.rank.rank_rows), and their best cells are listed. Frequency against saving: for each cell of
the Liberty file (the final set if it exists), how often its class occurs, its estimated saving, how
many instances the mappings with the new cells used (build/map_extended/<design>_extended_<script>.log,
where they exist), and how much of its cones is shared with logic outside the cut, which a new cell
cannot remove.

    python -m src.hd.analysis [--top 10]
        -> results/hd/per_design.csv, results/hd/per_design.txt, results/hd/frequency_vs_saving.csv,
           results/hd/frequency_vs_saving.txt
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from itertools import combinations

from src.aig import aiger, aigs
from src.aig.aigs import OUT as AIGS
from src.cut_enum import write_cuts
from src.hd.cut_classes import CUTS, pn_class, read, reduce_support
from src.hd.rank import MAPS, REQUIRED, rank_rows, ranked, cell_name, stat
from src.hd.request_writer import FINAL_SET, final_set, selected
from src.map_library.table1 import map_design
from src.paths import ROOT

ISA = ["risc8", "pic16", "p16c5x"]        # one instruction set (handout, section 9.3)
# the top modules of the two optional ISA designs, from Table 2 of the option 2 handout
ISA_TOPS = {"pic16": "PIC16C5x", "p16c5x": "P16C5x"}
ISA_CUTS = ROOT / "build/analysis/cuts"
EXTENDED_MAPS = ROOT / "build/map_extended"
OUT = ROOT / "results/hd"


def cut_file(design: str):
    return CUTS / f"{design}_abc.csv" if design in REQUIRED else ISA_CUTS / f"{design}_abc.csv"


def available() -> list[str]:
    """The required designs and the ISA designs, each with an ABC cut file and a baseline stat log."""
    return [d for d in [*REQUIRED, *ISA_TOPS]
            if cut_file(d).exists() and (MAPS / f"{d}_reduced_A.log").exists()]


def per_design(designs: list[str], top: int) -> dict[str, list[dict]]:
    """Each design's best `top` cells, ranked on that design alone."""
    out = {}
    for d in designs:
        rows, _, _ = rank_rows(read([cut_file(d)]), [d])
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


def prepare(design: str, top: str):
    """The cut file and baseline log of a design outside the required six, if they are missing.
    Its cuts go in build/analysis/cuts, so that the required designs' results/cuts stay as they are."""
    if not (ISA_CUTS / f"{design}_abc.csv").exists():
        aigs.write(design, top)
        write_cuts.write(design, "abc", out=ISA_CUTS)
    if not (MAPS / f"{design}_reduced_A.log").exists():
        map_design(design, top, "reduced", "A")


def shared_logic(names: list[str]) -> dict[str, dict]:
    """For each cell, over its occurrences in the required designs' ABC AIGs (smallest cone per root):
    how many have an inner cone node that also feeds logic outside the cut, and how many of the cone's
    AND nodes the new cell would remove (the root, and the inner nodes that feed nothing outside)."""
    keys = {}
    for c in selected(names=names):
        n = len(c["inputs"])
        keys[(n, pn_class(int(c["truth_table"], 16), n))] = c["name"]
    out = {name: dict(occurrences=0, shared=0, cone_nodes=0, removable_nodes=0) for name in keys.values()}
    for design in REQUIRED:
        aig = aiger.read(AIGS / f"{design}_abc.aig")
        ands = {lhs >> 1: (a >> 1, b >> 1) for lhs, a, b in aig.ands}
        users = defaultdict(set)
        for v, fanins in ands.items():
            for f in fanins:
                users[f].add(v)
        ports = {lit >> 1 for lit in aig.outputs} | {latch[1] >> 1 for latch in aig.latches}
        smallest = {}
        with (CUTS / f"{design}_abc.csv").open() as f:
            for row in csv.DictReader(f):
                leaves = tuple(map(int, row["leaves"].split()))
                table, n = reduce_support(int(row["truth_table"], 16), len(leaves))
                name = keys.get((n, pn_class(table, n))) if n > 1 else None
                key = (int(row["root"]), name)
                if name and (key not in smallest or int(row["cone_size"]) < smallest[key][0]):
                    smallest[key] = (int(row["cone_size"]), leaves)
        for (root, name), (_, leaves) in smallest.items():
            cone, stack = set(), [root]
            while stack:
                v = stack.pop()
                if v not in cone and v not in leaves and v in ands:
                    cone.add(v)
                    stack += ands[v]
            shared = {v for v in cone if v != root and (users[v] - cone or v in ports)}
            kept, stack = set(shared), list(shared)       # a shared node keeps everything under it
            while stack:
                for f in ands[stack.pop()]:
                    if f in cone and f not in kept:
                        kept.add(f)
                        stack.append(f)
            s = out[name]
            s["occurrences"] += 1
            s["shared"] += bool(shared)
            s["cone_nodes"] += len(cone)
            s["removable_nodes"] += len(cone) - len(kept)
    return out


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
    """The cells of the Liberty file: the final set if it exists, otherwise the default selection."""
    names = final_set() if FINAL_SET.exists() else [c["name"] for c in selected()]
    shared = shared_logic(names)
    rows = []
    for c in selected(names=names):
        uses = extended_instances(c["name"])
        s = shared[c["name"]]
        rows.append(dict(cell=c["name"], expression=c["expression"], occurrences=sum(c["occurrences"].values()),
                         estimated_saving_um2=c["saving_um2"]["total"], area_um2=c["area_um2"],
                         instances=sum(uses.values()) if uses else "",
                         shared_occurrences=s["shared"], cone_nodes=s["cone_nodes"],
                         removable_nodes=s["removable_nodes"],
                         **{f"instances_{k}": v for k, v in uses.items()}))
    rows.sort(key=lambda r: -r["occurrences"])
    lines = ["frequency against saving, the cells of the Liberty file, most frequent first:"]
    for r in rows:
        removable = f"{100 * r['removable_nodes'] / r['cone_nodes']:.0f}%" if r["cone_nodes"] else "-"
        lines.append(f"  {r['cell']}: {r['occurrences']} occurrences, estimated saving {r['estimated_saving_um2']} um2, "
                     f"used {r['instances'] if r['instances'] != '' else '?'} times in the mappings; "
                     f"{r['shared_occurrences']} occurrences share inner logic, {removable} of the cone nodes "
                     f"would be removed")
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
    for design, top in ISA_TOPS.items():
        prepare(design, top)

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
