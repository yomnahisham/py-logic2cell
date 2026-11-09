"""--style tuned: search beyond the handout's fixed widths for the cell with the best area x delay.

Candidates differ in the widths of the stages that drive only inside the cell (the output stage keeps
the drive's widths, the most a row holds without folding) and in the order of their series stacks.
Each candidate's best layout is drawn and checked; its delay and input capacitance are measured at the
table point of section 6; the smallest width x slowest delay wins, then the lowest input capacitance.
"""

from __future__ import annotations

import re
from dataclasses import replace
from functools import cache
from pathlib import Path

from src.cell.characterize import CAP_POINT, characterize
from src.cell.liberty_timing import read_setup
from src.cell.network import Cell
from src.cell.stress import stress
from src.cell.tools import PDK, TECH

MODEL = PDK / "libs.ref/sky130_fd_pr/spice"
DEVICE = {"n": "nfet_01v8", "p": "pfet_01v8_hvt"}
GATE_L = 0.15


@cache
def drc_min_width() -> float:
    """The narrowest transistor diff/tap.2 allows for standard devices (um), from the Magic deck."""
    m = re.search(r"edge4way \*poly allfetsstd (\d+) allfets 0 0 \\\s*\"Transistor width", TECH.read_text())
    return int(m[1]) / 1000


@cache
def model_widths(kind: str) -> tuple[float, ...]:
    """Widths (um) the PDK model of this transistor kind has a bin for at our gate length, no narrower than
    the DRC allows. The models are binned, so a width between bins has no model."""
    text = (MODEL / f"sky130_fd_pr__{DEVICE[kind]}.pm3.spice").read_text()
    bins = re.findall(r"lmin = ([\d.e+-]+) lmax = ([\d.e+-]+) wmin = ([\d.e+-]+) wmax = ([\d.e+-]+)", text)
    widths = {round((float(w0) + float(w1)) / 2 * 1e6, 3) for l0, l1, w0, w1 in bins
              if float(l0) * 1e6 <= GATE_L + 1e-6 <= float(l1) * 1e6 + 2e-6}
    return tuple(sorted(w for w in widths if w >= drc_min_width() - 1e-9))


def sizings(cell: Cell, wn: float, wp: float) -> list[tuple[str, Cell]]:
    """The cell with its inner stages at the narrowest model width, at the middle model width up to the
    drive's, and at the drive's widths; one stage has no inner stages and stays as it is."""
    out = next(s for s in cell.stages if s.output == cell.flat.output)
    if len(cell.stages) == 1:
        return [("drive widths", cell)]
    n = [w for w in model_widths("n") if w <= wn + 1e-9]
    p = [w for w in model_widths("p") if w <= wp + 1e-9]
    choices = {}
    for label, (wn_in, wp_in) in (("narrowest", (n[0], p[0])), ("middle", (n[len(n) // 2], p[len(p) // 2])),
                                  ("drive widths", (n[-1], p[-1]))):
        fets = tuple(f if f in out.fets else replace(f, w=wn_in if f.kind == "n" else wp_in) for f in cell.flat.fets)
        choices.setdefault((wn_in, wp_in), (f"{label}: inner stages {wn_in}/{wp_in} um",
                                            Cell(cell.stages, replace(cell.flat, fets=fets))))
    return list(choices.values())


def score(folder: Path, name: str, inputs: list[str], output: str, table: int) -> dict:
    """Slowest delay and the input capacitances of a built cell at the table point (section 6), from its
    extracted netlist, as the characterizer measures them."""
    stress(folder, name)
    grids = {pin: ([CAP_POINT[0]], [CAP_POINT[1]]) for pin in inputs}
    r = characterize(folder, name, f"{name}_sasb.spice", inputs, output, table, grids, read_setup(), tag="_point")
    delays = [t[0][0] for a in r["arcs"] for k, t in a["tables"].items() if k.startswith("cell_") and t[0][0] is not None]
    caps = [c["capacitance"] for c in r["pins"].values() if c["capacitance"] is not None]
    return dict(delay_ns=max(delays) if delays else None, cap_pf=sum(caps) if caps else None,
                errors=r["errors"], pins={p: c["capacitance"] for p, c in r["pins"].items()})
