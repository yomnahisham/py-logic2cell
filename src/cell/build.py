"""Build one cell from a request: network, layout, checks, simulation, response.

    python -m src.cell.build <request.json> [--hd inv_1]

Work files go in build/cells/<name>/, the response in cells/<name>/response.json.
--hd compares the result with an installed HD cell (option 1 handout, section 4.1).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from src.cell import abutment, compare, simulate, verify
from src.cell.layout import draw, place
from src.cell.network import (MAX_BREAKS, Cell, NetworkError, cell_check, cell_variants, euler_orders, schematic,
                               stage_variants)
from src.common.request import RequestError, read_request, write_response
from src.common.stage import expression, single_stage
from src.layer_check import check as layer_check

ROOT = Path(__file__).resolve().parents[2]
SIZES = {"hd": (0.65, 1.0)}
MAX_ORDERS = 40     # Euler orders tried per variant, fewest contacts first


def tool_version() -> str:
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.strip()
    return f"git:{sha}" if sha else "unknown"


def build(request_path: Path, hd: str | None = None) -> dict:
    try:
        request = read_request(request_path)
    except RequestError as error:
        data = json.loads(request_path.read_text())
        out = ROOT / "cells" / str(data.get("name", request_path.stem))
        return write_response(out / "response.json", str(data.get("request_id")), error.status, error.reason)

    name = request.name
    work = ROOT / "build/cells" / name
    out = ROOT / "cells" / name
    work.mkdir(parents=True, exist_ok=True)

    def refuse(reason):
        return write_response(out / "response.json", request.request_id, "fail", reason, cell=name,
                              tool_version=tool_version())

    if request.sizing not in SIZES:
        return refuse(f"sizing {request.sizing} not built yet")
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
    for variant in variants:
        errors = cell_check(variant, request.truth_table)
        if errors:
            return refuse("switch-level check: " + "; ".join(errors))
    multi = len(variants[0].stages) > 1
    if hd and not multi:
        variants = [v for v in variants if compare.same_netlist(v.flat, hd)]
        if not variants:
            return refuse(f"no series order of the network matches the transistors of {hd}")
    widths = compare.hd_sizes(hd) if hd and not multi else {}
    wn, wp = SIZES[request.sizing]

    # every series order and Euler path, the first MAX_ORDERS of each by contacts; a cell wired on
    # li alone wins over one that needs met1, then the narrowest, the first found on a tie
    best, tried, unrouted = None, 0, []
    for variant in variants:
        for order in euler_orders(variant.flat)[:MAX_ORDERS]:
            tried += 1
            try:
                plan = place(variant.flat, order, wn, wp, widths)
            except ValueError as error:
                unrouted.append(f"{' '.join(order.gates)}: {error}")
                continue
            key = (any(mcons for _, mcons, _ in plan.joins.values()), plan.width)
            if best is None or key[0] < best[0][0] or (key[0] == best[0][0] and key[1] < best[0][1] - 1e-9):
                best = (key, variant, order)
    if best is None:
        if not tried:
            return refuse(f"no common Euler path with at most {MAX_BREAKS} diffusion breaks")
        return refuse(f"no Euler order can be drawn: {'; '.join(unrouted[:3])}")
    _, cell, order = best
    stage = cell.flat
    component, meta = draw(name, stage, order, wn, wp, widths)
    meta.update(inputs=list(request.inputs), output=request.output, orders_tried=tried,
                orders_drawable=tried - len(unrouted))
    component.write_gds(str(work / f"{name}.gds"), with_metadata=False)
    (work / f"{name}.spice").write_text(schematic(stage, name, wn, wp, widths=widths))
    (work / f"{name}.json").write_text(json.dumps(meta, indent=2) + "\n")

    checks = verify.verify(work, name)
    abut = abutment.check(work, name)
    layers = layer_check(str(work / f"{name}.gds"))
    sim = simulate.simulate(work, name, request.truth_table)
    network = dict(fets=len(stage.fets), switch_check="pass")
    if multi:
        network["stages"] = [dict(inputs=list(s.inputs), output=s.output, fets=len(s.fets)) for s in cell.stages]
    report = dict(network=network, order=meta, checks=checks,
                  abutment=abut, layers="pass" if layers else "fail", simulation=sim)
    if hd:
        report["compare"] = compare.compare(work, name, hd)

    passed = (checks["drc"] == 0 and checks["lvs"] == checks["rc_lvs"] == "match" and abut["passed"]
              and layers and sim["passed"])
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
        files={"gds": f"cells/{name}/cell.gds", "report": f"cells/{name}/report.json"},
        checks={"drc": checks["drc"], "lvs": checks["lvs"], "rc_lvs": checks["rc_lvs"],
                "truth_table": "pass" if sim["passed"] else "fail", "abutment": abut["errors"],
                "layers": "pass" if layers else "fail"},
        tool_version=tool_version())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("request", type=Path)
    ap.add_argument("--hd")
    args = ap.parse_args()
    response = build(args.request.resolve(), args.hd)
    print(json.dumps(response, indent=2))
    sys.exit(0 if response["status"] == "pass" else 1)
