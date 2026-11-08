"""The whole option 2 flow on one design (option 2 handout, section 9.4: a design given on the day).

    python -m src.hd.demo <design.v> <top> [--limit 10] [--sv]
        -> build/demo/<design>/: cuts, class summary, ranking, Liberty file, mapping logs and netlists,
           and summary.txt (also printed)

Steps, each with the code the full flow uses:
  1. AIG before and after ABC                       src.aig.aigs.write
  2. cuts of up to 4 inputs, checked by simulation  src.cut_enum.write_cuts.write
  3. classes, and NPN classes                       src.hd.cut_classes
  4. baseline mapping, scripts A and B, with cec    src.map_library.table5.check
  5. cost, redundancy, area, ranking                src.hd.rank
  6. Liberty file with the best new cells           src.hd.liberty_writer
  7. mapping with the new cells, A and B, with cec  src.map_library.table5.check
  8. the Table 5 rows and the best of both
"""

from __future__ import annotations

import argparse
import inspect
import json
import shutil
import sys
from pathlib import Path

from src.aig import aigs
from src.cut_enum import write_cuts
from src.hd import liberty_writer, rank
from src.hd.cut_classes import read, summary
from src.map_library.table1 import LIBS
from src.map_library.table5 import check
from src.paths import ROOT

WORK = ROOT / "build/demo"


def aig(design: str, top: str, path: Path, sv: bool = False) -> dict:
    """Step 1. The AIG export reads given/designs/<design>.v; another file needs its path argument."""
    aigs.OUT.mkdir(parents=True, exist_ok=True)
    if not sv and path.resolve() == (ROOT / f"given/designs/{design}.v").resolve():
        return aigs.write(design, top)
    if "path" not in inspect.signature(aigs.write).parameters:
        raise SystemExit(f"{path} is not in given/designs/, and src.aig.aigs.write has no path argument yet")
    return aigs.write(design, top, path=path, sv=sv)


def main(argv: list[str]):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("design", type=Path, help="the design's Verilog file")
    parser.add_argument("top", help="its top module")
    parser.add_argument("--limit", type=int, default=10, help="new cells in the Liberty file")
    parser.add_argument("--sv", action="store_true", help="read the design as SystemVerilog")
    args = parser.parse_args(argv)
    if not args.design.is_file():
        raise SystemExit(f"no such file: {args.design}")
    design = args.design.stem
    work = WORK / design
    maps = work / "map"
    maps.mkdir(parents=True, exist_ok=True)
    # the tools run in a container that sees only the repository: work on a copy inside it
    source = Path("build/demo") / design / args.design.name
    if args.design.resolve() != (ROOT / source).resolve():
        shutil.copyfile(args.design, ROOT / source)
    lines = [f"demo: {args.design} (top {args.top})"]

    def say(text):
        lines.append(text)
        print(text, flush=True)

    sizes = aig(design, args.top, source, args.sv)
    say(f"1. AIG: {sizes['raw']['ands']} AND nodes, {sizes['raw']['latches']} latches; "
        f"{sizes['abc']['ands']} AND nodes after ABC")

    for kind in ("raw", "abc"):
        n = write_cuts.write(design, kind, out=work / "cuts")
        say(f"2. cuts ({kind}): {n}, every one checked by simulation")

    for row in summary(read(sorted((work / "cuts").glob(f"{design}_*.csv")))):
        if row["design"] == design:
            say(f"3. classes ({row['aig']}): {row['classes']} up to input order and output inversion "
                f"({row['classes_4']} of 4 inputs), {row['npn_classes']} NPN")

    baseline = {}
    for script in "AB":
        baseline[script] = check(str(source), args.top, LIBS["reduced"], script,
                                 maps / f"{design}_reduced_{script}", sv=args.sv)
        say(f"4. baseline, script {script}: {baseline[script]['area_um2']:.4f} um2, "
            f"cec {'pass' if baseline[script]['equivalent'] else 'FAIL'}")

    rank.main([*map(str, sorted((work / "cuts").glob(f"{design}_*.csv"))), "--maps", str(maps),
               "--designs", design, "--out", str(work)])
    ranked = json.loads((work / "ranked.json").read_text())["candidates"]
    positive = [c for c in ranked if c["saving_um2"]["total"] > 0 and c["buildable"]]
    say(f"5. {len(ranked)} candidates kept by Table 3, {len(positive)} buildable with a positive estimated saving")
    if not positive:
        say("   no new cell is expected to save area on this design; stopping here")
        (work / "summary.txt").write_text("\n".join(lines) + "\n")
        return

    lib = work / "hd_reduced_ext.lib"
    liberty_writer.main(["--ranked", str(work / "ranked.json"), "--limit", str(args.limit), "--out", str(lib)])
    for c in positive[:args.limit]:
        say(f"6. {c['name']}: {c['expression']}, {c['cost']['transistors']} transistors, {c['area_um2']} um2, "
            f"estimated saving {c['saving_um2']['total']} um2")

    say("7-8. design  script  baseline_um2  new_cells_um2  reduction  new_cell_instances  equivalence")
    extended = {}
    for script in "AB":
        extended[script] = check(str(source), args.top, str(lib), script, maps / f"{design}_extended_{script}",
                                 sv=args.sv)
        b, e = baseline[script]["area_um2"], extended[script]["area_um2"]
        say(f"     {design}  {script}  {b:.4f}  {e:.4f}  {100 * (b - e) / b:+.2f}%  "
            f"{extended[script]['new_cell_instances']}  {'pass' if extended[script]['equivalent'] else 'FAIL'}")
    best_b = min(r["area_um2"] for r in baseline.values())
    best_e = min(r["area_um2"] for r in extended.values())
    say(f"     best of both: {best_b:.4f} -> {best_e:.4f} um2 ({100 * (best_b - best_e) / best_b:+.2f}%)")
    (work / "summary.txt").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
