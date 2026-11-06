"""Real cells from Option 1's tool (option 2 handout, section 4, step 11; overview, Appendix A).

For each cell of the final set, the cell's maker answers its request with cells/<name>/response.json
and the Liberty file that response names in files.liberty. A returned cell is used only if:
  - the response's status is pass and it is for the requested cell (Appendix A: a cell whose status
    is not pass must not be used in a mapping);
  - its Liberty file holds exactly one cell group, with the requested name;
  - its pins are the request's inputs and output, with those directions;
  - its output's function gives the request's truth table;
  - it has an area, and a timing group for each input (section 6).
Otherwise the cell keeps its estimated entry, and the reason is reported.

    python -m src.hd.real_cells [--names <cell> ... | --final-set [<path>]]   -> results/hd/real_cells.csv

src.hd.liberty_writer --real puts the accepted cells in place of their estimated entries.
"""

from __future__ import annotations

from dataclasses import dataclass
import argparse
import csv
import json
import re
import sys
from pathlib import Path

from src.common.request import truth_table
from src.hd.liberty import _CELL_GROUP, _DIRECTION, _FUNCTION, _PIN_GROUP, _AREA, _braced_groups, _unescape
from src.hd.request_writer import add_choice_arguments, chosen_names, selected
from src.paths import ROOT

CELLS = ROOT / "cells"
OUT = ROOT / "results/hd/real_cells.csv"


@dataclass(frozen=True)
class RealCell:
    name: str
    group: str | None           # the cell group to use, None if the cell was refused
    reason: str                 # why it was refused, or "accepted"
    area_um2: float | None
    response: dict | None


def check_group(cand: dict, text: str) -> tuple[str, float]:
    """The one cell group of a returned Liberty file and its area; raises ValueError if it breaks a rule."""
    groups = list(_braced_groups(text, _CELL_GROUP))
    if len(groups) != 1:
        raise ValueError(f"the Liberty file holds {len(groups)} cell groups, not 1")
    name, body = groups[0]
    if name != cand["name"]:
        raise ValueError(f"the cell group is {name}, not {cand['name']}")
    area = _AREA.search(body)
    if area is None or float(area[1]) <= 0:
        raise ValueError("no positive area")
    pins = {}
    for pin, pin_body in _braced_groups(body, _PIN_GROUP):
        direction = _DIRECTION.search(pin_body)
        if direction:
            pins[pin] = (direction[1], pin_body)
    expected = {**{p: "input" for p in cand["inputs"]}, cand["output"]: "output"}
    found = {p: d for p, (d, _) in pins.items()}
    if found != expected:
        raise ValueError(f"pins {found}, expected {expected}")
    out_body = pins[cand["output"]][1]
    function = _FUNCTION.search(out_body)
    if function is None:
        raise ValueError("the output has no function")
    table = truth_table(_unescape(function[1]), tuple(cand["inputs"]))
    if table != int(cand["truth_table"], 16):
        raise ValueError(f"function {function[1]!r} gives 0x{table:X}, the request is {cand['truth_table']}")
    related = set(re.findall(r'related_pin\s*:\s*"([^"]+)"', out_body))
    missing = [p for p in cand["inputs"] if p not in related]
    if missing:
        raise ValueError(f"no timing group for {missing}")
    return f'  cell ("{name}") {{{body}}}\n', float(area[1])


def intake(cand: dict, cells: Path = CELLS) -> RealCell:
    """The returned cell for one candidate, accepted or refused with a reason."""
    path = cells / cand["name"] / "response.json"
    if not path.exists():
        return RealCell(cand["name"], None, "no response yet", None, None)
    response = json.loads(path.read_text())
    if response.get("status") != "pass":
        return RealCell(cand["name"], None, f"status {response.get('status')}: {response.get('reason')}", None,
                        response)
    if response.get("cell") != cand["name"]:
        return RealCell(cand["name"], None, f"the response is for {response.get('cell')}", None, response)
    liberty = (response.get("files") or {}).get("liberty")
    if not liberty:
        return RealCell(cand["name"], None, "the response names no Liberty file (files.liberty)", None, response)
    lib = ROOT / liberty if not Path(liberty).is_absolute() else Path(liberty)
    if not lib.exists():
        return RealCell(cand["name"], None, f"{liberty} does not exist", None, response)
    try:
        group, area = check_group(cand, lib.read_text())
    except ValueError as error:
        return RealCell(cand["name"], None, str(error), None, response)
    return RealCell(cand["name"], group, "accepted", area, response)


def report(cands: list[dict], real: list[RealCell], path: Path = OUT):
    """Estimated against real area, transistors and width, for every cell of the set."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cell", "buildable", "status", "estimated_um2", "real_um2", "area_error_percent",
                    "estimated_transistors", "real_transistors", "estimated_sites", "real_sites", "reason"])
        for c, r in zip(cands, real):
            resp = r.response or {}
            error = round(100 * (c["area_um2"] - r.area_um2) / r.area_um2, 2) if r.area_um2 else ""
            w.writerow([c["name"], c.get("buildable", True), "real" if r.group else "estimated", c["area_um2"],
                        r.area_um2 or "", error, c["cost"]["transistors"], resp.get("transistors", ""),
                        c.get("sites", ""), resp.get("width_sites", ""), r.reason])


def main(argv: list[str]):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    add_choice_arguments(parser, limit_default=None)
    args = parser.parse_args(argv)
    cands = selected(args.limit or 10, chosen_names(args))
    real = [intake(c) for c in cands]
    report(cands, real)
    for r in real:
        print(f"{r.name}: {r.reason}")
    print(f"{sum(r.group is not None for r in real)} of {len(real)} real -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main(sys.argv[1:])
