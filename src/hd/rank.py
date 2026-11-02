"""Cost, redundancy, area and ranking of the cut classes (option 2 handout, section 4, steps 4 to 7).

For every class found in the ABC-restructured AIGs of the required designs:
  - cost of every class (src.hd.cost.estimate): Option 1's structure where it can build the
    class (buildable), a Shannon-split estimate where it cannot;
  - polarity: of the class's two functions (t and !t, each up to input order), a buildable one
    first, then the cheaper, then the more frequent, then the smaller table;
  - redundancy (Table 3) against the full HD library, with the smallest HD cell that matches;
  - estimated area from the area model (src.hd.area_model);
  - estimated saving per design: (AND nodes its occurrences cover) x a_node - occurrences x
    (area of the new cell), where a_node is the design's baseline combinational area (script A,
    reduced library, flip-flops and latches taken out) over the AND nodes of its ABC AIG.

Every class Table 3 keeps is ranked; a candidate Option 1's structure cannot build is marked
buildable: false (overview, section 2, rule 3: the group may ask the instructor for it).
The ranking is a guess: cuts overlap and share logic (handout, section 4, step 7).

    python -m src.hd.rank [cut files]
        -> results/hd/candidates.csv, results/hd/redundancy_summary.txt,
           results/hd/a_node.csv, results/hd/ranked.json
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import argparse
import csv
import json
import os
import re
import sys

from src.common.stage import widen
from src.hd.area_model import fit
from src.hd.cost import estimate
from src.hd.cut_classes import Occurrences, class_id, cut_files, invert, p_class, read
from src.hd.liberty import cell_areas
from src.hd.redundancy import classify
from src.paths import PREFIX, ROOT
from src.map_library.table1 import DESIGNS

REQUIRED = list(DESIGNS)
RANK_AIG = "abc"
MAPS = ROOT / "results/map"
SIZES = ROOT / "results/aig_sizes.csv"
REDUCED = ROOT / "given/hd_reduced.lib"
OUT = ROOT / "results/hd"
NAMES = "ABCD"


def cell_name(table: int, n: int) -> str:
    return f"dd2_gc1__f{table:0{max(1, (1 << n) // 4)}x}_1"


def request_id(table: int, n: int) -> str:
    return f"GC1-{table:0{max(1, (1 << n) // 4)}X}"


def stat(path) -> tuple[float, dict[str, int]]:
    """Chip area and cell counts from the output of Yosys's stat -liberty."""
    text = open(path).read()
    area = float(re.findall(r"Chip area for module .*?:\s*([\d.]+)", text)[-1])
    return area, {name: int(count) for name, count in re.findall(r"^\s+(\S+)\s+(\d+)\s*$", text, re.M)}


def a_node(design: str, areas: dict, ands: dict[str, int], maps=MAPS) -> dict:
    """The design's baseline combinational area per AND node of its ABC AIG."""
    area, counts = stat(Path(maps) / f"{design}_reduced_A.log")
    sequential = sum(count * areas[name][0] for name, count in counts.items()
                     if name in areas and areas[name][1])
    return dict(design=design, area_um2=area, sequential_um2=round(sequential, 4),
                combinational_um2=round(area - sequential, 4), ands=ands[design],
                a_node_um2=round((area - sequential) / ands[design], 4))


def choose_polarity(n: int, key: int, occurrences: list[Occurrences]):
    """The class's function to build, and its estimate: buildable first, then the cheaper."""
    counts = defaultdict(int)
    for occ in occurrences:
        for p, c in occ.polarity_counts().items():
            counts[p] += c
    options = []
    for t in {p_class(key, n), p_class(invert(key, n), n)}:
        e = estimate(t, n)
        options.append((not e.buildable, e.transistors, e.stages, -counts[t], t, e))
    return min(options, key=lambda o: o[:5])[4:]


def decide(table3: str, est_area: float | None, hd_area: float, inv_area: float) -> tuple[str, str]:
    """Table 3's 'What to do' column."""
    if table3 == "exists":
        return "drop", "HD has it"
    if table3 == "exists_inv":
        if est_area is not None and est_area < hd_area + inv_area:
            return "keep", "smaller than the HD cell plus an inverter"
        return "drop", "not smaller than the HD cell plus an inverter"
    if table3 == "contained":
        if est_area is not None and est_area < hd_area:
            return "keep", "smaller than the HD cell"
        return "drop", "not smaller than the HD cell"
    return "keep", "HD lacks it"


def main(argv: list[str]):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("cuts", nargs="*", help="cut files (default: results/cuts/*.csv)")
    parser.add_argument("--maps", default=MAPS, help="folder of the baseline stat logs <design>_reduced_A.log")
    args = parser.parse_args(argv)
    aigs = read(cut_files(args.cuts))
    full = cell_areas(open(os.environ["HD_LIB_FULL"]).read())
    reduced = cell_areas(REDUCED.read_text())
    inv_area = full[PREFIX + "inv_1"][0]
    model = fit()
    with SIZES.open() as f:
        ands = {r["design"]: int(r[f"ands_{RANK_AIG}"]) for r in csv.DictReader(f)}
    nodes = {d: a_node(d, reduced, ands, args.maps) for d in REQUIRED}
    others = sorted(d for d, aig in aigs if aig == RANK_AIG and d not in REQUIRED)

    keys = sorted({k for d in REQUIRED for k in aigs[(d, RANK_AIG)].classes})
    rows = []
    for n, key in keys:
        occ = {d: aigs[(d, RANK_AIG)].classes.get((n, key), Occurrences()) for d in REQUIRED}
        table, e = choose_polarity(n, key, list(occ.values()))
        table3, hd_cell, note = classify(widen(table, n))
        hd_area = full[hd_cell][0] if hd_cell else None
        est = model.area(e.transistors)
        decision, why = decide(table3, est, hd_area, inv_area)
        saving = {d: round(o.cone_total * nodes[d]["a_node_um2"] - o.count * est, 4) for d, o in occ.items()}
        rows.append(dict(
            class_id=class_id(key, n), inputs=n, truth_table=f"0x{table:0{max(1, (1 << n) // 4)}X}",
            occurrences=sum(o.count for o in occ.values()), cone_nodes=sum(o.cone_total for o in occ.values()),
            table3=table3, hd_cell=(hd_cell or "").removeprefix(PREFIX), hd_area_um2=hd_area or "",
            buildable="yes" if e.buildable else "no", stages=e.stages, inverters=e.inverters,
            transistors=e.transistors, series=e.series, est_sites=model.sites(e.transistors), est_area_um2=est,
            decision=decision, why=why, saving_um2=round(sum(saving.values()), 4),
            _table=table, _estimate=e, _occ=occ, _saving=saving,
            _other={d: aigs[(d, RANK_AIG)].classes.get((n, key), Occurrences()).count for d in others}))

    OUT.mkdir(parents=True, exist_ok=True)
    public = [k for k in rows[0] if not k.startswith("_")]
    with (OUT / "candidates.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=public, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (-r["occurrences"], r["class_id"])))
    with (OUT / "a_node.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(nodes[REQUIRED[0]]))
        w.writeheader()
        w.writerows(nodes.values())
    (OUT / "redundancy_summary.txt").write_text(redundancy_summary(rows))

    ranked = sorted((r for r in rows if r["decision"] == "keep"), key=lambda r: (-r["saving_um2"], r["class_id"]))
    out = dict(
        aig=RANK_AIG, designs=REQUIRED,
        saving="sum over designs of cone_nodes x a_node - occurrences x area",
        a_node_um2={d: nodes[d]["a_node_um2"] for d in REQUIRED},
        model=dict(a=model.a, b=model.b, site_um=[model.site_w, model.site_h]),
        candidates=[candidate(i + 1, r) for i, r in enumerate(ranked)])
    (OUT / "ranked.json").write_text(json.dumps(out, indent=2) + "\n")
    print(open(OUT / "redundancy_summary.txt").read())
    for c in out["candidates"][:10]:
        print(c["rank"], c["name"], c["expression"], c["cost"]["transistors"], "T",
              c["area_um2"], "um2", "saving", c["saving_um2"]["total"])


def candidate(rank: int, r: dict) -> dict:
    table, n, e = r["_table"], r["inputs"], r["_estimate"]
    return dict(
        rank=rank, class_id=r["class_id"], name=cell_name(table, n), request_id=request_id(table, n),
        inputs=list(NAMES[:n]), output="Y", truth_table=r["truth_table"], expression=e.expression,
        buildable=e.buildable,
        cost=dict(stages=e.stages, inverters=e.inverters, transistors=e.transistors, series=e.series),
        sites=r["est_sites"], area_um2=r["est_area_um2"],
        redundancy=dict(table3=r["table3"], hd_cell=r["hd_cell"] or None, why=r["why"]),
        occurrences={d: o.count for d, o in r["_occ"].items()},
        cone_nodes={d: o.cone_total for d, o in r["_occ"].items()},
        saving_um2={**r["_saving"], "total": r["saving_um2"]},
        other_designs=r["_other"])


def redundancy_summary(rows: list[dict]) -> str:
    """How many candidate classes each class of Table 3 removed, with examples."""
    lines = [f"candidate classes (ABC AIGs of {', '.join(REQUIRED)}): {len(rows)}", ""]
    for t3 in ("exists", "exists_inv", "contained", "new"):
        group = sorted((r for r in rows if r["table3"] == t3), key=lambda r: (-r["occurrences"], r["class_id"]))
        decisions = defaultdict(int)
        for r in group:
            decisions[r["decision"]] += 1
        lines.append(f"{t3}: {len(group)} classes, {sum(r['occurrences'] for r in group)} occurrences; "
                     + ", ".join(f"{k} {v}" for k, v in sorted(decisions.items())))
        for r in group[:5]:
            lines.append(f"  {r['class_id']} {r['truth_table']} ({r['inputs']} inputs) x{r['occurrences']}: "
                         f"{r['hd_cell'] or '-'}, est {r['est_area_um2'] or '-'} um2 vs HD "
                         f"{r['hd_area_um2'] or '-'} um2 -> {r['decision']} ({r['why']})")
    kept = [r for r in rows if r["decision"] == "keep"]
    lines += ["", f"kept: {len(kept)}, of which with a positive estimated saving: "
                  f"{sum(r['saving_um2'] > 0 for r in kept)}",
              f"kept but not buildable with Option 1's structure (estimated by a Shannon split): "
              f"{sum(r['buildable'] == 'no' for r in kept)}, with a positive saving: "
              f"{sum(r['buildable'] == 'no' and r['saving_um2'] > 0 for r in kept)}"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main(sys.argv[1:])
