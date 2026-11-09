"""Finish a built cell for its requester (overview, Appendix A): characterize it, write its Liberty cell and
Verilog model, and add both to its response.

    python -m src.cell.deliver <request.json> [--grid-from <HD cell>] [--grid N]

The cell must have been built first (python -m src.cell.build <request.json>). The tables use the slew and
load indexes of the HD cell grid_from: by default the x1 HD cell with the same function (hd_twin), or inv_1
when HD has none (a new function).
"""

from __future__ import annotations

import argparse
import json
import re
from itertools import permutations
from pathlib import Path

from src.cell.characterize import characterize_ours
from src.cell.liberty_write import cell_group, library
from src.common.request import read_request
from src.hd.liberty import parse_function, parse_liberty_file
from src.paths import PREFIX

ROOT = Path(__file__).resolve().parents[2]
USABLE = ROOT / "given/hd_usable.lib"


def verilog(name: str, inputs: list[str], output: str, expression: str) -> str:
    """A functional model of the cell: one continuous assignment of the request's expression."""
    body = expression.replace("!", "~")
    ports = ", ".join(list(inputs) + [output])
    lines = [f"module {name} ({ports});"] + [f"    input {p};" for p in inputs] + [f"    output {output};",
             f"    assign {output} = {body};", "endmodule", ""]
    return "\n".join(lines)


def hd_twin(inputs: tuple[str, ...], table: int) -> tuple[str, dict[str, str]] | None:
    """The x1 HD cell (from given/hd_usable.lib) with the request's function, and our pin -> its pin;
    None for a function HD does not have. Functions are compared by truth table over every pin order."""
    for cell in sorted(parse_liberty_file(str(USABLE)), key=lambda c: (c.area or 0, c.name)):
        if not cell.name.endswith("_1") or len(cell.inputs) != len(inputs) or set(cell.support) != set(cell.inputs):
            continue
        _, evaluate = parse_function(cell.function)
        for pins in permutations(cell.inputs):
            if all(evaluate({p: bool(i >> k & 1) for k, p in enumerate(pins)}) == bool(table >> i & 1)
                   for i in range(1 << len(inputs))):
                return cell.name.removeprefix(PREFIX), dict(zip(inputs, pins))
    return None


def deliver(request_path: Path, grid_from: str | None = None, grid: int | None = None) -> dict:
    request = read_request(request_path)
    twin = hd_twin(request.inputs, request.truth_table)
    rename = twin[1] if twin and (grid_from or twin[0]) == twin[0] else None
    grid_from = grid_from or (twin[0] if twin else "inv_1")
    out = ROOT / "cells" / request.name
    response = json.loads((out / "response.json").read_text())
    if response["status"] != "pass":
        raise SystemExit(f"{request.name}: its build did not pass ({response.get('reason')}); nothing to deliver")
    timing = characterize_ours(request_path, grid_from, grid, rename=rename)
    if timing["errors"]:
        raise SystemExit(f"{request.name}: the characterizer reported errors: {timing['errors'][:3]}")
    if not re.fullmatch(r"[A-Za-z0-9_ ()!&|^]+", request.expression):
        raise SystemExit(f"{request.name}: expression {request.expression!r} has an operator Liberty may not read")
    group = cell_group(timing, response["area_um2"], request.expression)
    (out / "cell.lib").write_text(library(request.name, [timing], [group]))
    (out / "cell.v").write_text(verilog(request.name, list(request.inputs), request.output, request.expression))
    response["files"].update(liberty=f"cells/{request.name}/cell.lib", verilog=f"cells/{request.name}/cell.v")
    response["ngspice_sha256"] = timing["ngspice"]["sha256"]
    response["grid_from"] = timing["grid_from"]
    (out / "response.json").write_text(json.dumps(response, indent=2) + "\n")
    return response


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("request", type=Path)
    ap.add_argument("--grid-from", help="HD cell whose table indexes to use (default inv_1)")
    ap.add_argument("--grid", type=int, help="points per index, e.g. 5 for the 5x5 subset")
    args = ap.parse_args()
    print(json.dumps(deliver(args.request.resolve(), args.grid_from, args.grid), indent=2))
