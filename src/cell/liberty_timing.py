"""Read the characterization setup and one cell's timing from a Liberty file (option 1 handout, section 5).

    python -m src.cell.liberty_timing [cell, e.g. nand2_1]

Everything the characterizer needs to agree with HD comes from here, not from the code (Table 5, Setup):
the library's thresholds, voltage, temperature and units, and, per cell, the input slews and loads each
table is indexed by, the arcs, and the HD values the validation compares against.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from src.paths import LIBERTY_TT, PREFIX

SETUP_KEYS = [f"{kind}_threshold_pct_{edge}" for kind in ("input", "output", "slew_lower", "slew_upper")
              for edge in ("rise", "fall")] + ["slew_derate_from_library", "nom_voltage", "nom_temperature"]
UNIT_KEYS = ["time_unit", "voltage_unit", "capacitive_load_unit"]
TABLES = ("cell_rise", "cell_fall", "rise_transition", "fall_transition")


@dataclass
class Group:
    """One Liberty group: kind ("cell", "pin", "timing", ...), its arguments, simple and complex attributes."""
    kind: str
    args: list[str]
    attrs: dict = field(default_factory=dict)
    groups: list["Group"] = field(default_factory=list)

    def all(self, kind: str) -> list["Group"]:
        return [g for g in self.groups if g.kind == kind]


_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[{}();:,]|[^\s{}();:,"]+')


def parse(text: str) -> Group:
    """Parse Liberty text (one or more top-level groups) into a tree under a root group."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S).replace("\\\n", " ")
    tokens = _TOKEN.findall(text)
    pos = 0

    def unquote(t):
        return t[1:-1] if t.startswith('"') else t

    def body(group):
        nonlocal pos
        while pos < len(tokens) and tokens[pos] != "}":
            name = tokens[pos]
            pos += 1
            if tokens[pos] == ":":                      # simple attribute: name : value ;
                value = tokens[pos + 1]
                pos += 2
                if pos < len(tokens) and tokens[pos] == ";":
                    pos += 1
                group.attrs[name] = unquote(value)
            elif tokens[pos] == "(":                    # group or complex attribute: name ( args ) ...
                pos += 1
                args = []
                while tokens[pos] != ")":
                    if tokens[pos] != ",":
                        args.append(unquote(tokens[pos]))
                    pos += 1
                pos += 1
                if pos < len(tokens) and tokens[pos] == "{":
                    pos += 1
                    child = Group(name, args)
                    body(child)
                    pos += 1                            # the closing }
                    group.groups.append(child)
                else:
                    if pos < len(tokens) and tokens[pos] == ";":
                        pos += 1
                    group.attrs[name] = args
            else:
                raise ValueError(f"Liberty: unexpected {tokens[pos]!r} after {name!r}")

    root = Group("root", [])
    body(root)
    return root


def numbers(text: str) -> list[float]:
    return [float(v) for v in text.replace(",", " ").split()]


def read_setup(path: Path = LIBERTY_TT) -> dict:
    """The library-level attributes of SETUP_KEYS and UNIT_KEYS, from the header before the first cell."""
    text = path.read_text()
    head = text[:text.index("cell (")]
    out = {}
    for key in SETUP_KEYS:
        m = re.search(rf"^\s*{key}\s*:\s*([-+\d.eE]+)\s*;", head, re.M)
        if not m:
            raise ValueError(f"{path}: no {key} in the library header")
        out[key] = float(m[1])
    for key in UNIT_KEYS:
        m = re.search(rf"^\s*{key}\s*(?::\s*\"?([^\";]+)\"?|\(([^)]*)\))", head, re.M)
        if not m:
            raise ValueError(f"{path}: no {key} in the library header")
        out[key] = (m[1] or m[2]).replace('"', "").strip()
    return out


def cell_text(path: Path, name: str) -> str:
    """The text of one cell group, found by matching braces."""
    text = path.read_text()
    m = re.search(rf'cell\s*\(\s*"?{re.escape(name)}"?\s*\)\s*{{', text)
    if not m:
        raise ValueError(f"{path}: no cell {name}")
    depth, i = 0, m.end() - 1
    while True:
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
        if depth == 0:
            return text[m.start():i]


@dataclass
class Arc:
    pin: str                 # related_pin, the input
    output: str
    sense: str               # timing_sense
    when: str | None         # a state condition, if the library gives one
    tables: dict             # name -> {"index_1": [...], "index_2": [...], "values": [[...]]}


@dataclass
class CellTiming:
    name: str
    inputs: list[str]
    output: str
    function: str
    area: float
    capacitance: dict        # pin -> {"capacitance", "rise_capacitance", "fall_capacitance"}
    arcs: list[Arc]


def read_cell(name: str, path: Path = LIBERTY_TT) -> CellTiming:
    """Pins, input capacitances and timing arcs of one combinational cell. name may omit the HD prefix."""
    full = name if name.startswith(PREFIX) or path != LIBERTY_TT else PREFIX + name
    cell = parse(cell_text(path, full)).all("cell")[0]
    inputs, output, function, caps, arcs = [], None, None, {}, []
    for pin in cell.all("pin"):
        pname = pin.args[0]
        if pin.attrs.get("direction") == "input":
            inputs.append(pname)
            caps[pname] = {k: float(pin.attrs[k]) for k in ("capacitance", "rise_capacitance", "fall_capacitance")
                           if k in pin.attrs}
        elif pin.attrs.get("direction") == "output":
            if output is not None:
                raise ValueError(f"{full}: more than one output")
            output, function = pname, pin.attrs.get("function")
            for t in pin.all("timing"):
                tables = {}
                for g in t.groups:
                    if g.kind in TABLES:
                        rows = g.attrs["values"]
                        tables[g.kind] = {"index_1": numbers(g.attrs["index_1"][0]),
                                          "index_2": numbers(g.attrs["index_2"][0]),
                                          "values": [numbers(r) for r in rows]}
                arcs.append(Arc(t.attrs["related_pin"], pname, t.attrs.get("timing_sense", ""), t.attrs.get("when"),
                                tables))
    if output is None:
        raise ValueError(f"{full}: no output pin")
    return CellTiming(full, inputs, output, function, float(cell.attrs.get("area", 0)), caps, arcs)


if __name__ == "__main__":
    print(json.dumps(read_setup(), indent=2))
    if len(sys.argv) > 1:
        c = read_cell(sys.argv[1])
        print(f"{c.name}: {c.output} = {c.function}, inputs {c.inputs}, area {c.area}")
        for pin, cap in c.capacitance.items():
            print(f"  pin {pin}: {cap}")
        for a in c.arcs:
            t = a.tables["cell_rise"]
            print(f"  arc {a.pin} -> {a.output} {a.sense}{' when ' + a.when if a.when else ''}: "
                  f"{len(t['index_1'])}x{len(t['index_2'])}, slews {t['index_1']}, loads {t['index_2']}")
