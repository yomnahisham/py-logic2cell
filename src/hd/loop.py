"""Option 3 end to end on one design, in rounds: design -> candidate cells -> real cells -> the design mapped
again (the overview's Figure 1, with the loop closed).

    python -m src.hd.loop <design.v> <top> [--rounds 2] [--per-round 3] [--sv] [--build-minutes 90]
        -> build/loop/<design>/ (requests, mapped netlists of every round, rounds.csv, summary.txt)
           and results/hd/loop_<design>.txt

Once: the design's AIG, its checked cuts and their classes, and the ranking (src.hd.demo, steps 1 to 5),
against the reduced library. Then each round:
  1. the next --per-round candidates in rank order that no earlier round tried;
  2. each is requested from Option 1 (Appendix A), built, delivered and model-checked (src.cell.build,
     deliver, model_check); a cell already delivered for the same request is reused;
  3. Option 2's intake takes the returned Liberty cell or refuses it (src.hd.real_cells.intake);
  4. greedily, as step 10 of the handout: each accepted cell is kept only if the design's best-of-both area
     with it is smaller (both scripts mapped, cec on each);
  5. the design as mapped onto the reduced library plus every cell kept so far is the round's new design:
     its area (best of A and B), worst delay and power (OpenSTA, as src.hd.ppa) are recorded.
--rounds sets how many times this runs on the same input design; it stops early when no candidate is left.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

from src.cut_enum import write_cuts
from src.hd import rank
from src.hd.demo import aig
from src.hd.liberty import cell_areas
from src.hd.liberty_writer import extend
from src.hd.ppa import power
from src.hd.real_cells import intake
from src.hd.request_writer import request
from src.hd.sta import clocks, script as sta_script, sta, worst
from src.map_library.table1 import LIBS
from src.map_library.table5 import check
from src.paths import ROOT

WORK = ROOT / "build/loop"
TOLERANCE = 1e-4        # um2


def option1(cand: dict, req_dir: Path, minutes: float) -> str:
    """Request one cell from Option 1 and wait for it; returns what happened."""
    folder = ROOT / "cells" / cand["name"]
    path = req_dir / f"{cand['name']}.json"
    path.write_text(json.dumps(request(cand), indent=2) + "\n")
    response = folder / "response.json"
    if (folder / "cell.lib").exists() and (folder / "model_check.json").exists() and response.exists() \
            and json.loads(response.read_text()).get("status") == "pass":
        return "reused"
    py = str(ROOT / ".venv/bin/python")
    try:
        steps = (["-m", "src.cell.build", str(path)], ["-m", "src.cell.deliver", str(path)],
                 ["-m", "src.cell.model_check", str(path)])
        for step in steps:
            p = subprocess.run([py, *step], cwd=ROOT, capture_output=True, text=True, timeout=minutes * 60)
            if p.returncode:
                return f"{step[1].split('.')[-1]} failed"
    except subprocess.TimeoutExpired:
        return f"over {minutes:g} min"
    return "built"


def mapped(source: Path, top: str, lib: Path, tag: str, maps: Path, sv: bool) -> dict:
    """Both scripts on one library, with cec; the smaller-area one."""
    runs = {s: check(str(source), top, str(lib), s, maps / f"{tag}_{s}", sv=sv) for s in "AB"}
    best = min("AB", key=lambda s: runs[s]["area_um2"])
    return dict(runs=runs, script=best, area=runs[best]["area_um2"], netlist=maps / f"{tag}_{best}.v",
                cec=all(r["equivalent"] for r in runs.values()))


def measure(m: dict, lib: Path, top: str, seq: set, ours: list[str], work: Path) -> dict:
    netlist = m["netlist"]
    ports = clocks(netlist.read_text(), seq)
    t = worst(sta(sta_script(netlist, lib, top, ports), work / f"{netlist.stem}.sta.log"))
    p = power(netlist, lib, top, ports, 10.0, 0.1, ours)
    return dict(area_um2=m["area"], script=m["script"], cec="pass" if m["cec"] else "FAIL",
                worst_delay_ns=t["worst_delay_ns"], power_mw=round(p["power_w"] * 1e3, 6),
                ours_power_mw=round(p["ours_w"] * 1e3, 6))


def main(argv: list[str]):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("design", type=Path)
    ap.add_argument("top")
    ap.add_argument("--rounds", type=int, default=2, help="times through design -> cells -> new design")
    ap.add_argument("--per-round", type=int, default=3, help="candidates requested from Option 1 per round")
    ap.add_argument("--sv", action="store_true")
    ap.add_argument("--build-minutes", type=float, default=90, help="time limit per Option 1 step of a cell")
    args = ap.parse_args(argv)
    design = args.design.stem
    work = WORK / design
    maps, req_dir = work / "map", work / "requests"
    for d in (maps, req_dir):
        d.mkdir(parents=True, exist_ok=True)
    source = Path("build/loop") / design / args.design.name     # the containers see only the repository
    if args.design.resolve() != (ROOT / source).resolve():
        shutil.copyfile(args.design, ROOT / source)
    lines = [f"loop: {args.design} (top {args.top}), {args.rounds} rounds of {args.per_round} candidates"]

    def say(text):
        lines.append(text)
        print(text, flush=True)

    aig(design, args.top, source, args.sv)
    for kind in ("raw", "abc"):
        write_cuts.write(design, kind, out=work / "cuts")
    reduced = ROOT / LIBS["reduced"]
    base = mapped(source, args.top, reduced, f"{design}_reduced", maps, args.sv)
    rank.main([*map(str, sorted((work / "cuts").glob(f"{design}_*.csv"))), "--maps", str(maps),
               "--designs", design, "--out", str(work)])
    ranked = [c for c in json.loads((work / "ranked.json").read_text())["candidates"]
              if c["saving_um2"]["total"] > 0 and c["buildable"]]
    say(f"{len(ranked)} buildable candidates with a positive estimated saving")
    seq = {n for n, (_, s) in cell_areas(reduced.read_text()).items() if s}
    rows = [dict(round=0, tried="", kept="", **measure(base, reduced, args.top, seq, [], work))]
    say(f"round 0 (reduced library): {rows[0]}")
    kept, groups, tried = [], [], 0
    current = base
    lib = reduced
    for r in range(1, args.rounds + 1):
        batch = ranked[tried:tried + args.per_round]
        tried += len(batch)
        if not batch:
            say(f"round {r}: no candidate left")
            break
        notes = []
        for cand in batch:
            what = option1(cand, req_dir, args.build_minutes)
            real = intake(cand)
            if real.group is None:
                notes.append(f"{cand['name']} {what}, refused: {real.reason}")
                continue
            trial = work / f"round{r}_{cand['name']}.lib"
            trial.write_text(extend(reduced.read_text(), "".join(groups + [real.group])))
            m = mapped(source, args.top, trial, f"{design}_r{r}_{cand['name']}", maps, args.sv)
            if m["cec"] and m["area"] < current["area"] - TOLERANCE:
                kept.append(cand["name"])
                groups.append(real.group)
                current, lib = m, trial
                notes.append(f"{cand['name']} {what}, kept: {m['area']} um2")
            else:
                notes.append(f"{cand['name']} {what}, not kept: {m['area']} um2 (cec {'pass' if m['cec'] else 'FAIL'})")
        say(f"round {r}: " + "; ".join(notes))
        rows.append(dict(round=r, tried=" ".join(c["name"] for c in batch), kept=" ".join(kept),
                         **measure(current, lib, args.top, seq, kept, work)))
        say(f"round {r} design: {rows[-1]}")
    with (work / "rounds.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    b, e = rows[0], rows[-1]
    say(f"{design}: area {b['area_um2']} -> {e['area_um2']} um2 ({(e['area_um2'] - b['area_um2']) / b['area_um2'] * 100:+.2f}%), "
        f"worst delay {b['worst_delay_ns']} -> {e['worst_delay_ns']} ns, power {b['power_mw']} -> {e['power_mw']} mW, "
        f"cells kept: {', '.join(kept) or 'none'}")
    (work / "summary.txt").write_text("\n".join(lines) + "\n")
    (ROOT / "results/hd" / f"loop_{design}.txt").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
