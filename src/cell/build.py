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
from src.cell.layout import draw
from src.cell.network import NetworkError, build_stage, euler_order, schematic, switch_check
from src.common.request import RequestError, read_request, write_response
from src.layer_check import check as layer_check

ROOT = Path(__file__).resolve().parents[2]
SIZES = {"hd": (0.65, 1.0)}


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
        stage = build_stage(request.inputs, request.output, request.expression)
    except NetworkError as error:
        return refuse(str(error))
    errors = switch_check(stage, request.truth_table)
    if errors:
        return refuse("switch-level check: " + "; ".join(errors))
    order = euler_order(stage)
    if order is None:
        return refuse("no common Euler path (diffusion breaks not built yet)")

    wn, wp = SIZES[request.sizing]
    component, meta = draw(name, stage, order, wn, wp)
    meta.update(inputs=list(request.inputs), output=request.output)
    component.write_gds(str(work / f"{name}.gds"), with_metadata=False)
    (work / f"{name}.spice").write_text(schematic(stage, name, wn, wp))
    (work / f"{name}.json").write_text(json.dumps(meta, indent=2) + "\n")

    checks = verify.verify(work, name)
    abut = abutment.check(work, name)
    layers = layer_check(str(work / f"{name}.gds"))
    sim = simulate.simulate(work, name, request.truth_table)
    report = dict(network=dict(fets=len(stage.fets), switch_check="pass"), order=meta, checks=checks,
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
        cell=name, stages=1, transistors=len(stage.fets), width_sites=meta["width_sites"], area_um2=area,
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
