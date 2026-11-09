"""Build one cell from a request: network, layout, checks, simulation, response.

    python -m src.cell.build <request.json> [--hd inv_1]

Work files go in build/cells/<name>/, the response in cells/<name>/response.json, and every step
taken for the cell, in order, in cells/<name>/build.log.
--hd compares the result with an installed HD cell (option 1 handout, section 4.1).
"""

from __future__ import annotations

import argparse
import math
from concurrent.futures import ProcessPoolExecutor
import os
from dataclasses import replace
from collections import Counter
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.cell import abutment, compare, simulate, verify
from src.cell import tuned
from src.cell.tuned import drc_min_width
from src.cell.characterize import CAP_POINT
from src.cell.layout import GRID, N_DIFF, P_DIFF, SITE, draw, gate_runs, min_width, place, uses_met1
from src.cell.network import (MAX_BREAKS, Cell, NetworkError, Stage, cell_check, cell_variants, euler_orders,
                               schematic, stack_depths, stage_variants, cells_of,
                               operand_splits, split, build_stage)
from src.common.request import RequestError, read_request, write_response
from src.common.stage import expression, single_stage
from src.layer_check import check as layer_check

ROOT = Path(__file__).resolve().parents[2]
SIZES = {"hd": (0.65, 1.0), "stack": (0.65, 1.0)}    # x1 widths; stack multiplies them (stacked)
MAX_ORDERS = 40     # Euler orders tried per variant, fewest contacts first
TUNED_CANDIDATES = 4    # --style tuned: layouts drawn, checked and measured per cell
GROW_RETRY = 8          # orders given the targeted widening when they run out of tries (place's grow)
MAX_TOTAL_ORDERS = 420  # orders per cell over all its variants, narrowest bound first: maj3_1 has 416 and
                        # builds in about 25 minutes; or_and_maj has 1632 and ran for 9 hours without a cap
CELLS = {"handout": "cells", "tuned": "cells_tuned"}     # where each style writes its cells (and build/<it>/)
JOBS = int(os.getenv("CELL_JOBS", os.cpu_count() or 1))    # orders placed at once, one process each
MAX_SPLITS = 3      # levels of the decomposition fallback (network.operand_splits)
SPLITS_KEPT = 2     # networks carried to the next level: the cost of a level grows with every network kept
MORE_ORDERS = 200   # how far down the list the build goes when none of the first can be drawn
LI_RETRY, LI_TRIES = 5, 60      # orders drawn again for li alone when all need met1, and widenings each


def tool_version() -> str:
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.strip()
    return f"git:{sha}" if sha else "unknown"


class Trace:
    """The steps taken for one cell, written to build.log next to its response."""

    def __init__(self):
        self.lines = []

    def step(self, title):
        self.lines += ["", f"== {title}"]

    def __call__(self, *text):
        self.lines += [" ".join(str(t) for t in text)]

    def write(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(self.lines).lstrip("\n") + "\n")


def describe(plan, order, log: Trace):
    """Where everything went in the chosen layout, in um from the cell's left edge."""
    log(f"width {plan.width} um ({round(plan.width / 0.46)} sites), diffusion {plan.diff_x[0]} .. {plan.diff_x[1]}")
    log("gates  ", "  ".join(f"{g}@{x}" for g, x in zip(order.gates, plan.gate_x)))
    for row, nodes in (("n", order.n_nodes), ("p", order.p_nodes)):
        cols = []
        for j, (net, x) in enumerate(zip(nodes, plan.col_x)):
            if j in plan.cont[row]:
                cols.append(f"{net}@{x} {'wide' if plan.half[(row, j)] > 0.1 else 'narrow'} contacts y={plan.ys[(row, j)]}")
            else:
                cols.append(f"{net}@{x} no contact")
        log(f"{row}MOS columns:")
        for text in cols:
            log("   ", text)
        for net, x0, x1, edge in plan.lanes[row]:
            y0, y1 = plan.lane_y(row, net, x0, x1, edge)
            log(f"    lane {net} x {x0} .. {x1}, {edge} edge, y {round(y0, 3)} .. {round(y1, 3)}")
        for net, x in plan.jogs[row]:
            log(f"    jog {net} at x {x}")
        for (r, k), (under, z0, z1, y) in plan.notches.items():
            if r == row:
                log(f"    column {k} notched under the lane of {under}: x {round(z0, 3)} .. {round(z1, 3)}, li kept {'above' if row == 'p' else 'below'} y {round(y, 3)}")
    for gate, runs in plan.pads.items():
        for x, first, last in runs:
            log(f"poly contact {gate}@{x} for gates {first}..{last}, {'narrow' if x in plan.narrow else 'wide'} pad")
    for net, x in plan.crossing.items():
        log(f"crossing {net} at x {x}")
    for net, (li, mcons, track) in plan.joins.items():
        if mcons:
            log(f"met1 bridge {net}: mcons at {mcons}, track {track}")


def place_one(args):
    """place() in a worker process: (plan, None), or (None, why it cannot be drawn)."""
    try:
        return place(*args[:5], grow=args[5] if len(args) > 5 else True, bridges=args[6] if len(args) > 6 else False), None
    except ValueError as error:
        return None, str(error)


POOL = []      # the worker processes, started once per run


def run_all(fn, items: list) -> list:
    """fn over items, JOBS at a time in separate processes, results in the order of items."""
    if JOBS <= 1 or len(items) <= 1:
        return [fn(item) for item in items]
    if not POOL:
        POOL.append(ProcessPoolExecutor(max_workers=JOBS))
    return list(POOL[0].map(fn, items))


def sized(cell: Cell, hd: str | None, log) -> Cell:
    """Transistor widths of a cell of several stages: the handout's x1 widths everywhere, except that with
    --hd a cell that connects like the installed one takes its widths transistor by transistor, since
    Table 4 asks the transistors to match, every W and L."""
    if hd:
        flat = compare.with_hd_widths(cell.flat, hd)
        if flat is not None:
            log(f"widths copied from {hd}, transistor by transistor (it connects the same way)")
            return Cell(cell.stages, flat)
    return cell


def stacked(cell: Cell, wn: float, wp: float, log) -> Cell:
    """Tutorial 3's sizing (handout section 4, step 3): every transistor of the output stage is the x1 width
    times the depth of its series stack, folded into fingers that fit its diffusion row (Table 1); inner
    stages and inverters stay x1. As HD folds (nor3_2, nand3_2: A A B B C C), each transistor becomes k
    fingers between the same two nodes, which the Euler walk can put side by side under one poly contact;
    k is set per row, so the NMOS and PMOS rows may have different finger counts (unequal folding: the row
    with more fingers gets columns of its own). No finger is narrower than diff/tap.2 allows."""
    out = next(s for s in cell.stages if s.output == cell.flat.output)
    depth = stack_depths(out)
    row = {"n": N_DIFF[1] - N_DIFF[0], "p": P_DIFF[1] - P_DIFF[0]}
    want = {i: depth[i] * (wn if f.kind == "n" else wp) for i, f in enumerate(out.fets)}
    k = {kind: max([math.ceil(want[i] / row[kind] - 1e-9) for i, f in enumerate(out.fets) if f.kind == kind], default=1)
         for kind in "np"}
    widths = {i: round(max(math.ceil(want[i] / k[f.kind] / GRID - 1e-9) * GRID, drc_min_width()), 3)
              for i, f in enumerate(out.fets)}
    for i, f in enumerate(out.fets):
        log(f"{f.kind}MOS gate {f.gate} ({f.a} - {f.b}): {depth[i]} in series, {want[i]:g} um -> {k[f.kind]} x {widths[i]} um"
            + (" (diff/tap.2 minimum)" if widths[i] > want[i] / k[f.kind] + 1e-9 else ""))
    fets = tuple(replace(f, w=widths[i]) for i, f in enumerate(out.fets) for _ in range(k[f.kind]))
    stages = tuple(Stage(s.inputs, s.output, fets) if s is out else s for s in cell.stages)
    return Cell(stages, Stage(cell.flat.inputs, cell.flat.output, tuple(f for s in stages for f in s.fets)))


def output_contacts(plan, order, cell: Cell) -> int:
    """Diffusion contacts on the columns at the source and drain of the output stage's transistors: they
    sit in series with the cell's drive, so between layouts of one width the one with more is faster."""
    out = next(s for s in cell.stages if s.output == cell.flat.output).fets
    cols = {(row, k) for row, fets in (("n", order.n_fets), ("p", order.p_fets))
            for i, f in enumerate(fets) if f is not None and f in out for k in (i, i + 1)}
    return sum(len(plan.ys.get(col, [])) for col in cols)


def widths_vs_hd(stage, hd: str, wn: float, wp: float, widths: dict) -> str:
    """Whether our transistor widths are the installed cell's: per input gate, and over the gates on
    internal nets as a whole, since HD names those nets differently."""
    _, theirs = compare.hd_fets(hd)
    if len(theirs) != len(stage.fets):
        return f"widths not comparable with {hd}: it has {len(theirs)} transistors, ours {len(stage.fets)}"
    key = lambda kind, gate, w: (kind, gate if gate in stage.inputs else "internal", round(w, 4))
    ours = Counter(key(f.kind, f.gate, f.w or widths.get((f.kind, f.gate), wn if f.kind == "n" else wp))
                   for f in stage.fets)
    hd_ws = Counter(key(kind, gate, w) for kind, gate, _, _, w in theirs)
    if ours == hd_ws:
        return f"every transistor width matches {hd}'s"
    return f"widths differ from {hd}: ours only {sorted((ours - hd_ws).elements())}, HD only {sorted((hd_ws - ours).elements())}"


def make_cell(work: Path, name: str, stage, order, wn: float, wp: float, widths: dict, request) -> dict:
    """Draw one layout in work/, write its GDS, schematic and plan, and run every check on it."""
    work.mkdir(parents=True, exist_ok=True)
    component, meta = draw(name, stage, order, wn, wp, widths)
    meta.update(inputs=list(request.inputs), output=request.output)
    component.write_gds(str(work / f"{name}.gds"), with_metadata=False)
    (work / f"{name}.spice").write_text(schematic(stage, name, wn, wp, widths=widths))
    (work / f"{name}.json").write_text(json.dumps(meta, indent=2) + "\n")
    checks = verify.verify(work, name)
    abut = abutment.check(work, name)
    layers = layer_check(str(work / f"{name}.gds"))
    sim = simulate.simulate(work, name, request.truth_table)
    passed = (checks["drc"] == 0 and checks["lvs"] == checks["rc_lvs"] == "match" and abut["passed"]
              and layers and sim["passed"])
    return dict(meta=meta, checks=checks, abut=abut, layers=layers, sim=sim, passed=passed)


def build(request_path: Path, hd: str | None = None, style: str = "handout", place_only: bool = False) -> dict:
    log = Trace()
    log(f"build {request_path.name}{f' --hd {hd}' if hd else ''}, style {style}, {tool_version()}, "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    log.step("1. request")
    try:
        request = read_request(request_path)
    except RequestError as error:
        data = json.loads(request_path.read_text())
        out = ROOT / CELLS[style] / str(data.get("name", request_path.stem))
        log(f"refused ({error.status}): {error.reason}")
        log.write(out / "build.log")
        return write_response(out / "response.json", str(data.get("request_id")), error.status, error.reason)

    name = request.name
    work = ROOT / "build" / CELLS[style] / name
    out = ROOT / CELLS[style] / name
    work.mkdir(parents=True, exist_ok=True)
    log(f"name {name}, id {request.request_id}, inputs {', '.join(request.inputs)}, output {request.output}, "
        f"truth table 0x{request.truth_table:0{max(1, (1 << len(request.inputs)) // 4)}x}, sizing {request.sizing}")

    def refuse(reason):
        log(f"refused: {reason}")
        log.write(out / "build.log")
        return write_response(out / "response.json", request.request_id, "fail", reason, cell=name,
                              tool_version=tool_version())

    if request.sizing not in SIZES:
        return refuse(f"sizing {request.sizing} not built yet")
    log.step("2. network")
    try:
        # one stage when the truth table allows it, otherwise a split into stages;
        form = single_stage(request.truth_table, len(request.inputs))
        if form:
            stages = stage_variants(request.inputs, request.output, expression(form, list(request.inputs)))
            variants = [Cell((s,), s) for s in stages]
        else:
            variants = cell_variants(request.inputs, request.output, request.truth_table)
    except NetworkError as error:
        return refuse(str(error))
    log("one stage" if form else "split into stages", f"({len(variants)} series orders)")
    for i, variant in enumerate(variants):
        log(f"variant {i}:", " | ".join(f"{s.output} = f({', '.join(s.inputs)}), {len(s.fets)} fets" for s in variant.stages))
        for fet in variant.flat.fets:
            log(f"    {fet.kind}MOS gate {fet.gate}: {fet.a} - {fet.b}")
    log.step("3. switch-level check")
    for i, variant in enumerate(variants):
        errors = cell_check(variant, request.truth_table)
        if errors:
            return refuse("switch-level check: " + "; ".join(errors))
        log(f"variant {i}: every input combination gives the truth table")
    multi = len(variants[0].stages) > 1
    if hd and not multi and style == "handout":       # tuned tries every series order
        kept = [v for v in variants if compare.same_netlist(v.flat, hd)]
        log(f"kept {len(kept)} of {len(variants)} variants that connect like the installed {hd} "
            f"(Table 4: the transistors must match HD's; the others differ only in series order)")
        variants = kept
        if not variants:
            return refuse(f"no series order of the network matches the transistors of {hd}")
    widths = compare.hd_sizes(hd) if hd and not multi and style == "handout" else {}
    wn, wp = SIZES[request.sizing]
    log(f"widths: NMOS {wn} um, PMOS {wp} um" + (f", HD's own per gate: {widths}" if widths else ""))
    plain = variants
    if multi and style == "handout":
        variants = [sized(v, hd, log) for v in variants]
    if request.sizing == "stack":
        log("stack sizing, the first variant's transistors (the others alike):")
        variants = [stacked(v, wn, wp, log if i == 0 else lambda *a: None) for i, v in enumerate(variants)]
    if hd:
        log(widths_vs_hd(variants[0].flat, hd, wn, wp, widths))

    bridges = request.sizing == "stack"    # met1 along a row only where li has already failed (layout.place)

    def search(variants):
        """The best (key, variant, order, plan) over the orders of these variants, orders tried, and why
        the others could not be drawn. Orders are placed CELL_JOBS at a time, narrowest bound first; an
        order whose bound is wider than an li-only plan already found is skipped, since it cannot win.
        The choice is the same however the work is split: ties go to the order that comes first.

        An order whose bound is wider than a plan already found is skipped. Against an li-only plan it
        cannot win; against one that needs met1 it could only win with a wider plan on li alone, and a
        site of area is not spent to save a met1 bridge inside the cell (li still wins at equal width)."""
        best, tried, unrouted, met1_plans, found = None, 0, [], [], []
        orders = [euler_orders(variant.flat) for variant in variants]
        if request.sizing == "stack":
            # folded fingers: an order that keeps each input's fingers together needs the fewest poly
            # contacts, which decide whether it can be drawn at all (gate_runs)
            orders = [sorted(o, key=lambda order: sum(len(r) for r in gate_runs(order).values())) for o in orders]
        for start, stop in ((0, MAX_ORDERS), (MAX_ORDERS, MORE_ORDERS)):
            if best is not None:
                break
            if start:
                log(f"none of those can be drawn: the next ones, up to {MORE_ORDERS} per variant")
            tasks = []
            for i, variant in enumerate(variants):
                for k, order in enumerate(orders[i][start:stop], start):
                    try:
                        bound = min_width(order, wn, wp, widths)
                    except ValueError:
                        bound = 0       # place() will say why it cannot be drawn
                    tasks.append((bound, i, k, variant, order))
            tasks.sort(key=lambda t: t[:3])
            if len(tasks) > MAX_TOTAL_ORDERS:
                log(f"{len(tasks)} orders over all variants: the {MAX_TOTAL_ORDERS} with the narrowest bound are tried, "
                    f"the other {len(tasks) - MAX_TOTAL_ORDERS} (at least {tasks[MAX_TOTAL_ORDERS][0]} um) are not")
                tasks = tasks[:MAX_TOTAL_ORDERS]
            results = {}
            for at in range(0, len(tasks), 2 * JOBS):
                batch = [t for t in tasks[at:at + 2 * JOBS] if not (best and t[0] > best[0][1] + 1e-9)]
                for t in tasks[at:at + 2 * JOBS]:
                    if t not in batch:
                        results[t[1:3]] = (t, None, f"skipped: at least {t[0]} um, wider than the {best[0][1]} um found")
                for t, (plan, error) in zip(batch, run_all(place_one, [(t[3].flat, t[4], wn, wp, widths, False, bridges) for t in batch])):
                    results[t[1:3]] = (t, plan, error)
                    if plan is not None:
                        out_cont, all_cont = output_contacts(plan, t[4], t[3]), sum(map(len, plan.ys.values()))
                        key = (uses_met1(plan), round(plan.width, 4), -out_cont, -all_cont)
                        found.append((key, t[3], t[4], plan, t[1:3]))
                        if best is None or (key, t[1:3]) < (best[0], best[4]):
                            best = (key, t[3], t[4], plan, t[1:3])
            # the orders that ran out of tries and could still beat the best plan get the targeted widening
            # (place's grow), the narrowest GROW_RETRY of them; it is too costly to run for every order
            retry = sorted((t for t, plan, error in results.values() if plan is None and error.startswith("gave up")
                            and (best is None or t[0] < best[0][1] - 1e-9)), key=lambda t: t[:3])[:GROW_RETRY]
            for t, (plan, error) in zip(retry, run_all(place_one, [(t[3].flat, t[4], wn, wp, widths, True, bridges) for t in retry])):
                results[t[1:3]] = (t, plan, error if plan is None else None)
                if plan is not None:
                    out_cont, all_cont = output_contacts(plan, t[4], t[3]), sum(map(len, plan.ys.values()))
                    key = (uses_met1(plan), round(plan.width, 4), -out_cont, -all_cont)
                    found.append((key, t[3], t[4], plan, t[1:3]))
                    if best is None or (key, t[1:3]) < (best[0], best[4]):
                        best = (key, t[3], t[4], plan, t[1:3])
            for (i, k) in sorted(results):
                (bound, _, _, variant, order), plan, error = results[(i, k)]
                tried += 1
                text = f"variant {i} gates {' '.join(order.gates)} | n {' '.join(order.n_nodes)} | p {' '.join(order.p_nodes)}"
                if plan is None:
                    if not error.startswith("skipped"):
                        unrouted.append(f"{' '.join(order.gates)}: {error}")
                    log(f"{text}: {'cannot draw: ' if not error.startswith('skipped') else ''}{error}")
                    continue
                out_cont, all_cont = output_contacts(plan, order, variant), sum(map(len, plan.ys.values()))
                log(f"{text}: {plan.width} um{', met1 inside' if uses_met1(plan) else ''}, "
                    f"{out_cont} contacts on the output stage, {all_cont} in all")
                if uses_met1(plan):
                    met1_plans.append((round(plan.width, 4), variant, order))
        best = best[:4] if best else None
        # li inside before met1 (handout step 5): when every order needed met1, the narrowest few are drawn
        # again, widened further in search of a plan on li alone
        if best is not None and best[0][0]:
            log(f"every order needs met1: the {LI_RETRY} narrowest again, up to {LI_TRIES} more widenings each, for li alone")
            for _, variant, order in sorted(met1_plans, key=lambda t: t[0])[:LI_RETRY]:
                try:
                    plan = place(variant.flat, order, wn, wp, widths, li_tries=LI_TRIES)
                except ValueError:
                    continue
                if uses_met1(plan):
                    continue
                out_cont, all_cont = output_contacts(plan, order, variant), sum(map(len, plan.ys.values()))
                log(f"variant {variants.index(variant)} gates {' '.join(order.gates)}: {plan.width} um on li alone, "
                    f"{out_cont} contacts on the output stage, {all_cont} in all")
                key = (False, round(plan.width, 4), -out_cont, -all_cont)
                if key < best[0]:
                    best = (key, variant, order, plan)
        return best, tried, unrouted, found

    # every series order and Euler path, the first MAX_ORDERS of each by contacts; a cell wired on
    # li alone wins over one that needs met1, then the narrowest, the first found on a tie
    log.step(f"4. Euler orders and placement (first {MAX_ORDERS} per variant, fewest contacts first)")
    if style == "tuned":
        labels = {}
        expanded = []
        for i, v in enumerate(plain):
            for label, sized_cell in tuned.sizings(v, wn, wp):
                labels[id(sized_cell)] = f"series order {i}, {label}"
                expanded.append(sized_cell)
        log(f"tuned: {len(expanded)} candidates (series orders x widths of the inner stages); the output stage "
            f"keeps {wn}/{wp} um; widths from the model bins, none under the DRC's {tuned.drc_min_width()} um")
        variants = expanded
    best, tried, unrouted, found = search(variants)
    if best is None and style == "handout":
        # handout step 2, "otherwise decompose the function": no order of the network can be drawn, so one
        # operand of its largest stage becomes a stage of its own (network.operand_splits); while nothing can
        # be drawn, the largest stage of each split is split again, up to MAX_SPLITS levels
        networks = [[(tuple(request.inputs), request.output, expression(form, list(request.inputs)))] if form
                    else split(request.inputs, request.output, request.truth_table)]
        for level in range(1, MAX_SPLITS + 1):
            options = []
            for stages in networks:
                k = max(range(len(stages)), key=lambda i: len(build_stage(*stages[i]).fets))
                if len(build_stage(*stages[k]).fets) <= 4:
                    continue        # a stage of two inputs is as small as a split gets
                m = f"{stages[k][1]}_m{level if level > 1 else ''}"
                options += [stages[:k] + sub + stages[k + 1:] for sub in operand_splits(*stages[k], m=m)]
            networks = options[:SPLITS_KEPT]
            if not networks:
                break
            log(f"no order can be drawn ({'; '.join(unrouted[:2])}); split level {level}: {len(networks)} networks")
            variants = []
            for st in networks:
                log("split: " + " | ".join(f"{o} = {e}" for _, o, e in st))
                for cell in cells_of(request.inputs, request.output, st):
                    errors = cell_check(cell, request.truth_table)
                    if errors:
                        return refuse("switch-level check of a split: " + "; ".join(errors))
                    variants.append(cell)
            log(f"every split variant gives the truth table at switch level ({len(variants)} variants)")
            bridges = True
            best, tried, unrouted, found = search(variants)
            if best is not None:
                break
    if best is None:
        if not tried:
            return refuse(f"no common Euler path with at most {MAX_BREAKS} diffusion breaks")
        return refuse(f"no Euler order can be drawn: {'; '.join(unrouted[:3])}")
    _, cell, order, plan = best
    if place_only:      # a coverage run (src/cell/coverage.py): whether and how wide it can be drawn, no views
        return dict(status="placed", cell=name, stages=len(cell.stages), transistors=len(cell.flat.fets),
                    width_sites=round(plan.width / SITE), met1=uses_met1(plan), gates=list(order.gates))
    built = None
    if style == "tuned":
        # the best layout of each candidate, at most a site wider than the narrowest and on the same layers,
        # drawn, checked and measured at the table point; the smallest width x slowest delay wins
        per = {}
        for f in sorted(found, key=lambda f: (f[0], f[4])):
            per.setdefault(id(f[1]), f)
        pool = [f for f in per.values() if f[0][0] == best[0][0] and f[0][1] <= best[0][1] + SITE + 1e-9]
        pool = sorted(pool, key=lambda f: (f[0], f[4]))[:TUNED_CANDIDATES]
        log.step(f"5a. tuned: {len(pool)} candidates drawn, checked and measured at {CAP_POINT[0] * 1000:g} ps, "
                 f"{CAP_POINT[1] * 1000:g} fF")
        scored = []
        for n, (key, variant, order_n, plan_n, _) in enumerate(pool):
            folder = work / f"cand{n}"
            res = make_cell(folder, name, variant.flat, order_n, wn, wp, widths, request)
            text = f"candidate {n} ({labels[id(variant)]}), gates {' '.join(order_n.gates)}, {plan_n.width} um"
            if not res["passed"]:
                log(f"{text}: a check failed, left out")
                continue
            sc = tuned.score(folder, name, list(request.inputs), request.output, request.truth_table)
            if sc["delay_ns"] is None:
                log(f"{text}: no delay measured ({'; '.join(sc['errors'][:2])}), left out")
                continue
            value = plan_n.width * sc["delay_ns"]
            log(f"{text}: slowest delay {sc['delay_ns'] * 1000:.1f} ps, input capacitance {sc['cap_pf'] * 1000:.3f} fF, "
                f"width x delay {value * 1000:.1f} um.ps")
            scored.append(((round(value, 9), round(sc["cap_pf"], 9), n), variant, order_n, plan_n, folder, res, sc))
        if scored:
            _, cell, order, plan, folder, built, sc = min(scored, key=lambda t: t[0])
            log(f"chosen: candidate {min(scored, key=lambda t: t[0])[0][2]} ({labels[id(cell)]})")
            shutil.copytree(folder, work, dirs_exist_ok=True)
    log.step("5. chosen layout")
    log(f"variant {variants.index(cell)}, gates {' '.join(order.gates)}: li only beats met1, then the narrowest, "
        f"then the most contacts on the output stage, then the most contacts, the first found on a tie")
    describe(plan, order, log)
    stage = cell.flat
    built = built or make_cell(work, name, stage, order, wn, wp, widths, request)
    meta, checks, abut, layers, sim = built["meta"], built["checks"], built["abut"], built["layers"], built["sim"]
    meta.update(inputs=list(request.inputs), output=request.output, orders_tried=tried,
                orders_drawable=tried - len(unrouted), style=style)
    (work / f"{name}.json").write_text(json.dumps(meta, indent=2) + "\n")
    network = dict(fets=len(stage.fets), switch_check="pass")
    if len(cell.stages) > 1:
        network["stages"] = [dict(inputs=list(s.inputs), output=s.output, fets=len(s.fets)) for s in cell.stages]
    report = dict(network=network, order=meta, checks=checks,
                  abutment=abut, layers="pass" if layers else "fail", simulation=sim)
    if hd:
        report["compare"] = compare.compare(work, name, hd)

    log.step("6. checks")
    log(f"DRC (Magic, in a row with tap cells): {checks['drc']} errors" + (f": {checks['drc_why']}" if checks.get("drc_why") else ""))
    log(f"LVS (Netgen): {checks['lvs']}; RC-LVS: {checks['rc_lvs']}")
    log(f"abutment: {'pass' if abut['passed'] else 'fail'}, {abut['errors']} errors")
    log(f"layer check: {'pass' if layers else 'fail'}")
    log(f"simulation (ngspice): {'pass' if sim['passed'] else 'fail'}")
    if hd:
        log(f"compared with {hd}: see report.json, key compare")

    passed = built["passed"]
    log.step("7. response")
    log(f"{'pass' if passed else 'fail'}, {meta['width_sites']} sites, {round(meta['width'] * 2.72, 4)} um2")
    log.write(out / "build.log")
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(work / f"{name}.gds", out / "cell.gds")
    shutil.copy(work / f"{name}.spice", out / "cell.spice")
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    if hd:
        shutil.copy(work / f"{name}_vs_hd.png", out / "vs_hd.png")
    area = round(meta["width"] * 2.72, 4)
    return write_response(
        out / "response.json", request.request_id, "pass" if passed else "fail",
        None if passed else "a check failed, see report.json",
        cell=name, stages=len(cell.stages), transistors=len(stage.fets), width_sites=meta["width_sites"], area_um2=area,
        files={"gds": f"{CELLS[style]}/{name}/cell.gds", "report": f"{CELLS[style]}/{name}/report.json"},
        checks={"drc": checks["drc"], "lvs": checks["lvs"], "rc_lvs": checks["rc_lvs"],
                "truth_table": "pass" if sim["passed"] else "fail", "abutment": abut["errors"],
                "layers": "pass" if layers else "fail"},
        tool_version=tool_version())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("request", type=Path)
    ap.add_argument("--hd")
    ap.add_argument("--style", choices=["handout", "tuned"], default="handout",
                    help="handout: the handout's widths; tuned: search widths and stack orders for width x delay")
    args = ap.parse_args()
    response = build(args.request.resolve(), args.hd, args.style)
    print(json.dumps(response, indent=2))
    sys.exit(0 if response["status"] == "pass" else 1)
