"""The extended Liberty file: hd_reduced.lib plus the new cells (option 2 handout, section 6).

Each new cell's function, truth table and area come from results/hd/ranked.json (the cells
src.hd.request_writer.selected picks: by default the best 10 that have a positive saving and that
Option 1's structure can build). Capacitance and timing are placeholders from a simple
logical-effort model anchored on HD's inv_1, read from hd_reduced.lib:
  - input capacitance: inv_1's input capacitance x (transistors the input drives) / 2, since
    every HD finger has the same width;
  - delay: inv_1's delay at the table point nearest REF_SLEW and REF_LOAD, times the series
    depth of the network that drives each edge, summed over the stages from the input to Y;
  - output transition: inv_1's, times the depth of the last stage's network;
  - timing_sense: from the function (positive, negative or non-unate in that input).

    python -m src.hd.liberty_writer [--limit 10 | --names <cell> ... | --final-set [<path>]]
                                    [--scale <cell>=<factor> ...] [--out <lib>]
        -> libs/new_cells.lib (the new cell groups), build/libs/hd_reduced_ext.lib (the whole file);
           with --out, only the whole file, at that path (for the greedy selection's trials)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from src.common.stage import FULL, widen
from src.hd.cost import Cost, cost, gated, rises
from src.hd.liberty import _CELL_GROUP, _PIN_GROUP, _braced_groups
from src.hd.request_writer import LIMIT, add_choice_arguments, chosen_names, selected
from src.paths import PREFIX, ROOT

REDUCED = ROOT / "given/hd_reduced.lib"
NEW_CELLS = ROOT / "libs/new_cells.lib"
EXTENDED = ROOT / "build/libs/hd_reduced_ext.lib"
# Option 1 handout, section 6: HD cells are compared at the table point nearest 100 ps and 10 fF
# (the library's units are ns and pF)
REF_SLEW, REF_LOAD = 0.1, 0.01
TABLES = ("cell_rise", "cell_fall", "rise_transition", "fall_transition")


def _numbers(text: str) -> list[float]:
    return [float(x) for x in re.split(r"[,\s]+", text.strip()) if x]


def reference(text: str, cell: str = PREFIX + "inv_1") -> dict[str, float]:
    """inv_1's input capacitance and its four timing values at the reference point."""
    templates = {}
    for name, body in _braced_groups(text, re.compile(r'\blu_table_template\s*\(\s*"([^"]+)"\s*\)\s*')):
        templates[name] = re.findall(r'variable_\d\s*:\s*"?(\w+)"?', body)
    body = dict(_braced_groups(text, _CELL_GROUP))[cell]
    pins = dict(_braced_groups(body, _PIN_GROUP))
    out = {"capacitance": float(re.search(r"\bcapacitance\s*:\s*([\d.]+)", pins["A"])[1])}
    for table in TABLES:
        m = re.search(table + r'\s*\(\s*"([^"]+)"\s*\)\s*\{(.*?)\}', pins["Y"], re.S)
        variables = templates[m[1]]
        i1 = _numbers(re.search(r'index_1\s*\(\s*"([^"]*)"', m[2])[1])
        i2 = _numbers(re.search(r'index_2\s*\(\s*"([^"]*)"', m[2])[1])
        rows = [_numbers(r) for r in re.findall(r'"([^"]*)"', re.search(r"values\s*\((.*?)\)\s*;", m[2], re.S)[1])]
        target = {"input_net_transition": REF_SLEW, "total_output_net_capacitance": REF_LOAD}
        near1 = min(range(len(i1)), key=lambda j: abs(i1[j] - target[variables[0]]))
        near2 = min(range(len(i2)), key=lambda j: abs(i2[j] - target[variables[1]]))
        out[table] = rows[near1][near2]
    return out


def timing_sense(t: int, k: int) -> str:
    up, down = rises(t, k), rises(FULL ^ t, k)
    return "non_unate" if up and down else "positive_unate" if up else "negative_unate"


def depths(c: Cost, k: int) -> dict[str, int]:
    """Series depths from input k to Y, as multipliers of inv_1's four timing values."""
    complex_stage, inverter = (c.form.down, c.form.up), (1, 1)
    paths = []
    if (k, False) in c.signals:
        paths.append([complex_stage])
    if (k, True) in c.signals:
        paths.append([inverter, complex_stage])
    paths = [p + [inverter] * c.out_inverter for p in paths]
    out = {}
    for edge, table in (("rise", "cell_rise"), ("fall", "cell_fall")):
        worst = 0
        for path in paths:
            total, e = 0, edge
            for down, up in reversed(path):     # every stage inverts: the edge flips going back
                total += up if e == "rise" else down
                e = "fall" if e == "rise" else "rise"
            worst = max(worst, total)
        out[table] = worst
    last = inverter if c.out_inverter else complex_stage
    out["rise_transition"], out["fall_transition"] = last[1], last[0]
    return out


def cell_group(cand: dict, ref: dict[str, float]) -> str:
    n = len(cand["inputs"])
    table = int(cand["truth_table"], 16)
    c = cost(table, n)
    if c is None or c.transistors != cand["cost"]["transistors"]:
        raise ValueError(f"{cand['name']}: the cost does not match ranked.json")
    t = widen(table, n)
    lines = [f'  cell ("{cand["name"]}") {{', f"    area : {cand['area_um2']};"]
    for k, pin in enumerate(cand["inputs"]):
        cap = ref["capacitance"] * gated(c, k) / 2
        lines.append(f'    pin ("{pin}") {{ direction : "input"; capacitance : {cap:.6f}; }}')
    lines += [f'    pin ("{cand["output"]}") {{', '      direction : "output";',
              f'      function : "{cand["expression"]}";']
    for k, pin in enumerate(cand["inputs"]):
        scale = depths(c, k)
        lines += ["      timing () {", f'        related_pin : "{pin}";',
                  f'        timing_sense : "{timing_sense(t, k)}";']
        lines += [f'        {tb} (scalar) {{ values ("{ref[tb] * scale[tb]:.4f}"); }}' for tb in TABLES]
        lines.append("      }")
    lines += ["    }", "  }"]
    return "\n".join(lines) + "\n"


def extend(library: str, groups: str) -> str:
    """The library with the cell groups added before its final closing brace."""
    end = library.rstrip().rfind("}")
    return library[:end] + groups + library[end:]


def parse_scale(items: list[str] | None) -> dict[str, float]:
    """--scale <cell>=<factor> arguments as {cell: factor}."""
    scale = {}
    for item in items or []:
        name, _, factor = item.partition("=")
        try:
            value = float(factor)
        except ValueError:
            raise SystemExit(f"--scale needs <cell>=<factor>, got {item!r}") from None
        if not name or value <= 0:
            raise SystemExit(f"--scale needs a cell name and a positive factor, got {item!r}")
        scale[name] = value
    return scale


def groups(cells: list[dict], library: str, scale: dict[str, float] | None = None) -> str:
    """The cell groups of `cells`, with the area of each cell in `scale` multiplied by its factor
    (section 4, step 12: one cell made 30% smaller is a factor of 0.7)."""
    scale = scale or {}
    unknown = set(scale) - {c["name"] for c in cells}
    if unknown:
        raise SystemExit(f"--scale names cells that are not in the library: {sorted(unknown)}")
    ref = reference(library)
    return "".join(cell_group({**c, "area_um2": round(c["area_um2"] * scale.get(c["name"], 1), 4)}, ref)
                   for c in cells)


def main(argv: list[str]):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    add_choice_arguments(parser, limit_default=LIMIT)
    parser.add_argument("--scale", nargs="+", metavar="CELL=FACTOR", help="multiply these cells' areas")
    parser.add_argument("--out", type=Path, help="write only this whole library (libs/new_cells.lib is left alone)")
    args = parser.parse_args(argv)
    library = REDUCED.read_text()
    cells = selected(args.limit, chosen_names(args))
    text = groups(cells, library, parse_scale(args.scale))
    out = args.out or EXTENDED
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(extend(library, text))
    written = [out]
    if args.out is None:
        header = ("/* New cells for hd_reduced.lib, written by src/hd/liberty_writer.py from results/hd/ranked.json.\n"
                  "   Areas are estimates from the area model; capacitance and timing are placeholders\n"
                  f"   scaled from {PREFIX}inv_1 at {REF_SLEW} ns and {REF_LOAD} pF. */\n")
        NEW_CELLS.parent.mkdir(parents=True, exist_ok=True)
        NEW_CELLS.write_text(header + text)
        written.insert(0, NEW_CELLS)
    print(f"{len(cells)} new cells -> {', '.join(map(str, written))}")


if __name__ == "__main__":
    main(sys.argv[1:])
