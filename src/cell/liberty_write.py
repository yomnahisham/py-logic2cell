"""Write Liberty from the characterizer's timing JSON (option 1 handout, sections 3.3 and 5.1).

    python -m src.cell.liberty_write validation [cells ...] [--tag T]

`validation` writes the six reference cells as characterized for Table 5 (build/char/<cell>/..._timing.json):
  - libs/char_validation<tag>.lib: a library of only those cells, for the "Liberty syntax" row;
  - build/sta/hd_tt_ours<tag>.lib: a copy of the HD TT Liberty with those six cell groups replaced by ours,
    for the "Design level" row.

A cell group carries what the characterizer measured: the input capacitances and, per arc, its timing sense
and the four delay and transition tables on the characterizer's own indexes. Area, function and footprint
are given by the caller (for an HD cell, its own). The header (units, thresholds, templates, operating
conditions) is the HD Liberty's, copied, so the tables mean what HD's mean. The ngspice version and SHA256
of the runs are written at the top, and one library never mixes two builds (section 5).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.cell.liberty_timing import TABLES, cell_text, parse, read_cell
from src.paths import LIBERTY_TT, PREFIX

ROOT = Path(__file__).resolve().parents[2]
CELLS = ["inv_1", "nand2_1", "nor2_1", "nand3_1", "a21oi_1", "o21ai_1"]   # section 4.1
POWER = [("VGND", "primary_ground", "VNB"), ("VNB", "pwell", None), ("VPB", "nwell", None),
         ("VPWR", "primary_power", "VPB")]


def num(v: float) -> str:
    return f"{v:.10f}"


def table(kind: str, index_1: list[float], index_2: list[float], values: list[list[float | None]], pad: str) -> str:
    if any(v is None for row in values for v in row):
        raise ValueError(f"{kind}: missing entries, a table with holes is not written")
    rows = f', \\\n{pad}        '.join('"' + ", ".join(num(v) for v in row) + '"' for row in values)
    return (f'{pad}{kind} ("del_1_{len(index_1)}_{len(index_2)}") {{\n'
            f'{pad}    index_1 ("{", ".join(num(v) for v in index_1)}");\n'
            f'{pad}    index_2 ("{", ".join(num(v) for v in index_2)}");\n'
            f'{pad}    values ({rows});\n'
            f'{pad}}}\n')


def cell_group(timing: dict, area: float, function: str, footprint: str | None = None) -> str:
    """The Liberty cell group of one characterized cell."""
    name, output = timing["cell"], timing["output"]
    out = [f'    cell ("{name}") {{', f"        area : {num(area)};"]
    if footprint:
        out.append(f'        cell_footprint : "{footprint}";')
    for pin, kind, bias in POWER:
        out += [f'        pg_pin ("{pin}") {{', f'            pg_type : "{kind}";', f'            voltage_name : "{pin}";']
        out += [f'            related_bias_pin : "{bias}";'] if bias else []
        out.append("        }")
    for pin in timing["inputs"]:
        c = timing["pins"].get(pin)
        if c is None or None in (c["capacitance"], c["rise_capacitance"], c["fall_capacitance"]):
            raise ValueError(f"{name}: no capacitance for pin {pin}")
        out += [f'        pin ("{pin}") {{', '            direction : "input";',
                f"            capacitance : {num(c['capacitance'])};",
                f"            rise_capacitance : {num(c['rise_capacitance'])};",
                f"            fall_capacitance : {num(c['fall_capacitance'])};",
                '            related_ground_pin : "VGND";', '            related_power_pin : "VPWR";', "        }"]
    out += [f'        pin ("{output}") {{', '            direction : "output";', f'            function : "{function}";',
            '            related_ground_pin : "VGND";', '            related_power_pin : "VPWR";']
    for arc in timing["arcs"]:
        out += ["            timing () {", f'                related_pin : "{arc["pin"]}";',
                f'                timing_sense : "{arc["sense"]}";', '                timing_type : "combinational";']
        for kind in TABLES:
            if kind in arc["tables"]:
                out.append(table(kind, arc["index_1"], arc["index_2"], arc["tables"][kind], " " * 16).rstrip("\n"))
        out.append("            }")
    out += ["        }", "    }"]
    return "\n".join(out) + "\n"


def header(source: Path = LIBERTY_TT) -> str:
    """The library header of source: everything before its first cell group."""
    text = source.read_text()
    return text[:text.index("cell (")].rstrip(" ")


def templates(head: str, groups: list[dict]) -> str:
    """lu_table_template groups for any table size the header does not define (a subset grid)."""
    out = []
    for g in groups:
        for arc in g["arcs"]:
            name = f"del_1_{len(arc['index_1'])}_{len(arc['index_2'])}"
            if f'lu_table_template ("{name}")' not in head and name not in "".join(out):
                out.append(f'    lu_table_template ("{name}") {{\n        variable_1 : "input_net_transition";\n'
                           f'        variable_2 : "total_output_net_capacitance";\n    }}\n')
    return "".join(out)


def one_build(runs: list[dict]) -> dict:
    builds = {(r["ngspice"]["version"], r["ngspice"]["sha256"]) for r in runs}
    if len(builds) != 1 or None in next(iter(builds)):
        raise ValueError(f"runs from more than one ngspice build, or an unknown one: {builds}")
    return runs[0]["ngspice"]


def stamp(ngspice: dict) -> str:
    return (f"/* Characterized by py-logic2cell (src/cell/characterize.py) with {ngspice['version']}, "
            f"sha256 {ngspice['sha256']}, image {ngspice['image']} */\n")


def library(name: str, runs: list[dict], cells: list[str]) -> str:
    """A library of the given cell groups under the HD header, renamed to name."""
    head = header()
    first = head.index("{") + 1
    head = f'library ("{name}") {{' + head[first:]
    return stamp(one_build(runs)) + head + templates(head, runs) + "".join(cells) + "}\n"


def replace(source: Path, groups: dict[str, str], ngspice: dict) -> str:
    """source with the cell groups named in groups replaced, everything else unchanged."""
    text = source.read_text()
    for name, group in groups.items():
        old = cell_text(source, name)
        if text.count(old) != 1:
            raise ValueError(f"{source.name}: cell {name} found {text.count(old)} times")
        text = text.replace(old, group.strip())
    return stamp(ngspice) + text


def validation(cells: list[str], tag: str = "") -> tuple[Path, Path]:
    runs, groups = [], {}
    for short in cells:
        #load char results
        r = json.loads((ROOT / "build/char" / short / f"{PREFIX}{short}_timing{tag}.json").read_text())
        hd = read_cell(short)
        foot = parse(cell_text(LIBERTY_TT, hd.name)).all("cell")[0].attrs.get("cell_footprint")
        runs.append(r)
        groups[hd.name] = cell_group(r, hd.area, hd.function, foot)
    own = ROOT / "libs" / f"char_validation{tag}.lib"
    own.parent.mkdir(exist_ok=True)
    own.write_text(library(f"char_validation{tag}", runs, list(groups.values())))
    copy = ROOT / "build/sta" / f"hd_tt_ours{tag}.lib"
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_text(replace(LIBERTY_TT, groups, one_build(runs)))
    return own, copy


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["validation"])
    ap.add_argument("cells", nargs="*", default=CELLS)
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    for path in validation(args.cells, args.tag):
        print(f"-> {path}")
