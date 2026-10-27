"""Abutment: a generated cell next to HD cells, checked with DRC.

For each neighbour (tap, inv_1, fill_1): neighbour on the left, on the right,
the cell mirrored, and a second row flipped onto the shared VPWR and VGND
rails. Every row has a tap cell at each end.

    python -m src.cell.abutment build/cells/<name>
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import klayout.db as kdb

from src.cell.tools import TECH, run
from src.paths import GDS as HD_GDS, LEF, PREFIX

NEIGHBOURS = ("tapvpwrvgnd_1", "inv_1", "fill_1")
HEIGHT = 2.72


def lef_width(macro: str) -> float:
    """tap and fill cells have no prBoundary in the GDS, so take the width from the LEF."""
    text = LEF.read_text()
    body = text[text.index(f"MACRO {macro}\n"):]
    return float(re.search(r"SIZE\s+([\d.]+)\s+BY", body)[1])


def build_case(folder: Path, name: str, width: float, neighbour: str, how: str) -> str:
    layout = kdb.Layout()
    layout.read(str(HD_GDS))
    own = kdb.Layout()
    own.read(str(folder / f"{name}.gds"))
    cell = layout.create_cell(name)
    cell.copy_tree(own.top_cell())
    hd = {n: layout.cell(PREFIX + n) for n in set(NEIGHBOURS) | {"tapvpwrvgnd_1"}}
    widths = {n: lef_width(PREFIX + n) for n in hd}
    widths[name] = width

    def row(top, items, y=0.0, flip=False):
        x = 0.0
        for item, mirror in items:
            c = cell if item == name else hd[item]
            w = widths[item]
            if flip:
                t = kdb.DTrans(2 if mirror else 0, True, x + (w if mirror else 0), y)
            else:
                t = kdb.DTrans(2, True, x + w, y) if mirror else kdb.DTrans(x, y)
            top.insert(kdb.DCellInstArray(c.cell_index(), t))
            x += w

    case = f"{name}__{neighbour}__{how}"
    top = layout.create_cell(case)
    tap = ("tapvpwrvgnd_1", False)
    me, nb = (name, False), (neighbour, False)
    if how == "left":
        row(top, [tap, nb, me, tap])
    elif how == "right":
        row(top, [tap, me, nb, tap])
    elif how == "mirrored":
        row(top, [tap, nb, (name, True), (neighbour, True), tap])
    elif how == "flip_vpwr":
        row(top, [tap, me, tap])
        row(top, [tap, nb, tap], y=2 * HEIGHT, flip=True)
    elif how == "flip_vgnd":
        row(top, [tap, me, tap])
        row(top, [tap, nb, tap], y=0.0, flip=True)
    top.flatten(True)
    for info in [(67, 5), (68, 5), (64, 5), (64, 59), (83, 44)]:
        index = layout.find_layer(*info)
        if index is not None:
            top.shapes(index).clear()
    options = kdb.SaveLayoutOptions()
    options.select_cell(top.cell_index())
    layout.write(str(folder / f"{case}.gds"), options)
    return case


def check(folder: Path, name: str) -> dict:
    width = json.loads((folder / f"{name}.json").read_text())["width"]
    cases = [build_case(folder, name, width, nb, how) for nb in NEIGHBOURS
             for how in ("left", "right", "mirrored", "flip_vpwr", "flip_vgnd")]
    script = [f"tech load {TECH}", "drc style drc(full)"]
    for case in cases:
        script += [f"gds read {case}.gds", f"load {case}", "select top cell", "drc check", "drc catchup",
                   f'puts "DRC_COUNT {case} [drc list count total]"']
    script += ['puts "MAGIC_DONE"', "quit -noprompt"]
    out = run("magic", ["-dnull", "-noconsole", "-rcfile", "/dev/null"], folder,
              folder / f"{name}_abutment.log", stdin="\n".join(script) + "\n")
    if "MAGIC_DONE" not in out:
        raise RuntimeError(f"Magic stopped early, see {folder / f'{name}_abutment.log'}")
    counts = {k: int(v) for k, v in re.findall(r"^DRC_COUNT (\S+) (\d+)", out, re.M)}
    result = {"cases": counts, "errors": sum(counts.values()), "passed": len(counts) == len(cases)
              and not any(counts.values())}
    (folder / f"{name}_abutment.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    folder = Path(sys.argv[1]).resolve()
    result = check(folder.parent, folder.name)
    for case, n in result["cases"].items():
        print(f"{case:50s} {n}")
    print("PASS" if result["passed"] else "FAIL", f"{len(result['cases'])} cases, {result['errors']} DRC errors")
    sys.exit(0 if result["passed"] else 1)
