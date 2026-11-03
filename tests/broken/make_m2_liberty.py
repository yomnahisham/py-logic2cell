"""Broken cases for the extended Liberty file. Run from the repo root; writes build/broken/.

From given/hd_reduced.lib with the handout's example cell (given/examples/new_cell_example.lib,
its timing group filled in for B, C and D as its comment says):
  m2_liberty_ok.lib         the reference: loads and maps
  m2_liberty_syntax.lib     unbalanced parenthesis in the function: read_liberty must reject it
  m2_liberty_brace.lib      the cell group is not closed: ABC must fail with both scripts
  m2_liberty_no_timing.lib  no timing groups (an observation, not a broken case: see the test)
  m2_maj4n.v                a design that computes nothing but the example cell's function
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, ".")
from src.hd.liberty_writer import extend

OUT = Path("build/broken")
OUT.mkdir(parents=True, exist_ok=True)
library = Path("given/hd_reduced.lib").read_text()
example = Path("given/examples/new_cell_example.lib").read_text()
cell = example[example.index("  cell ("):]
timing = re.search(r"      timing \(\) \{.*?\n      \}\n", cell, re.S)[0]
cell = cell.replace("      /* one timing group like this for each of B, C and D */\n",
                    "".join(timing.replace('"A"', f'"{pin}"') for pin in "BCD"))
function = re.search(r'function : "([^"]*)"', cell)[1]

(OUT / "m2_liberty_ok.lib").write_text(extend(library, cell))
(OUT / "m2_liberty_syntax.lib").write_text(extend(library, cell.replace(function, function[:-1])))
(OUT / "m2_liberty_brace.lib").write_text(extend(library, cell.rstrip()[:-1]))
(OUT / "m2_liberty_no_timing.lib").write_text(
    extend(library, re.sub(r"      timing \(\) \{.*?\n      \}\n", "", cell, flags=re.S)))
(OUT / "m2_maj4n.v").write_text(
    f"module maj4n(input A, B, C, D, output Y);\n  assign Y = {function};\nendmodule\n")
