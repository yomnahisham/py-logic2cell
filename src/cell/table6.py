"""Table 6 cells against the installed HD cells (Option 1 handout, section 6): width and area.

    python -m src.cell.table6 [--sizings]   -> results/table6_vs_hd.csv (--sizings: only results/nor3_sizings.csv)

Run after the cells are built (build/cells/<name>/ must hold their GDS and extraction). The five
Table 6 functions that are also reference cells (section 4.1) are compared as built with --hd.
Delay and slew at the HD table point nearest 100 ps and 10 fF (section 6) come from our characterization
(build/cells/<name>/<name>_timing.json, written by src.cell.deliver on the HD cell's own grid) against the
shipped HD Liberty at the same entry. Pins are matched by function (deliver.hd_twin), so our A, B, C meet
HD's A1, A2, B1. Each cell's delay is the slowest cell_rise/cell_fall over its pins, its slew the slowest
rise/fall_transition; results/table6_timing.csv has every pin and table. The characterizer's own error
against the shipped Liberty (results/char_validation.txt) is the uncertainty of these comparisons.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from src.cell import compare
from src.cell.characterize import CAP_POINT, characterize, nearest
from src.cell.liberty_timing import read_setup
from src.cell.stress import stress
from src.cell.deliver import hd_twin
from src.cell.liberty_timing import read_cell
from src.common.request import truth_table
from src.cell.layout import HEIGHT, SITE

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results/table6_vs_hd.csv"
TIMING_OUT = ROOT / "results/table6_timing.csv"
DELAYS, SLEWS = ("cell_rise", "cell_fall"), ("rise_transition", "fall_transition")

# (our cell, installed HD cell, function as in Table 6)
PAIRS = [
    ("nand2_1", "nand2_1", "!(A & B)"),
    ("nor2_1", "nor2_1", "!(A | B)"),
    ("nand3_1", "nand3_1", "!(A & B & C)"),
    ("nor3_1", "nor3_1", "!(A | B | C)"),
    ("a21oi_1", "a21oi_1", "!((A & B) | C)"),
    ("o21ai_1", "o21ai_1", "!((A | B) & C)"),
    ("a22oi_1", "a22oi_1", "!((A & B) | (C & D))"),
    ("o22ai_1", "o22ai_1", "!((A | B) & (C | D))"),
    ("and2_1", "and2_1", "A & B"),
    ("a21o_1", "a21o_1", "(A & B) | C"),
    ("mux2_1", "mux2_1", "(A & !C) | (B & C)"),
    ("maj3_1", "maj3_1", "(A & B) | (C & (A | B))"),
    ("xor2_1", "xor2_1", "A ^ B"),
    ("o31ai_1", "o31ai_1", "!((A1 | A2 | A3) & B1)"),    # our choice (Table 6, last row)
]


def hd_at(short: str, points: dict) -> dict:
    """The installed HD cell, extracted and characterized with our flow, at one (slew, load) per pin:
    the fair comparison, since both sides then carry the same characterizer error."""
    hd = read_cell(short)
    folder = compare.hd_reference(ROOT / "build/char" / short, short)
    stress(folder, hd.name)
    grids = {pin: ([s], [l]) for pin, (s, l) in points.items()}
    return characterize(folder, hd.name, f"{hd.name}_sasb.spice", hd.inputs, hd.output,
                        truth_table(hd.function, tuple(hd.inputs)), grids, read_setup(), tag="_t6point")


def timing(cell: str, short: str, function: str) -> list[dict]:
    """Per pin and table: ours and the shipped HD value at the entry nearest 100 ps / 10 fF."""
    ours = json.loads((ROOT / "build/cells" / cell / f"{cell}_timing.json").read_text())
    pins = tuple(ours["inputs"])
    twin = hd_twin(pins, int(ours["truth_table"], 16))     # the table over its own pins (A1, A2, B1 or A, B, C)
    if not twin or twin[0] != short:
        raise ValueError(f"{cell}: {function} is not {short}'s function")
    lib = [a for a in read_cell(short).arcs if not a.when]
    at = {arc["pin"]: (nearest(arc["index_1"], CAP_POINT[0]), nearest(arc["index_2"], CAP_POINT[1])) for arc in ours["arcs"]}
    flow = hd_at(short, {twin[1][a["pin"]]: (a["index_1"][at[a["pin"]][0]], a["index_2"][at[a["pin"]][1]])
                         for a in ours["arcs"]})
    flow_arcs = {a["pin"]: a for a in flow["arcs"]}
    out = []
    for arc in ours["arcs"]:
        i, j = nearest(arc["index_1"], CAP_POINT[0]), nearest(arc["index_2"], CAP_POINT[1])
        hd_pin = twin[1][arc["pin"]]
        for table, values in arc["tables"].items():
            theirs = [a.tables[table] for a in lib if a.pin == hd_pin and table in a.tables]
            if not theirs or values[i][j] is None:
                continue
            h = max(t["values"][nearest(t["index_1"], arc["index_1"][i])][nearest(t["index_2"], arc["index_2"][j])]
                    for t in theirs)
            f = flow_arcs[hd_pin]["tables"][table][0][0]
            out.append(dict(cell=cell, hd=compare.PREFIX + short, pin=arc["pin"], hd_pin=hd_pin, value=table,
                            slew_ns=arc["index_1"][i], load_pf=arc["index_2"][j], ours_ns=round(values[i][j], 5),
                            hd_flow_ns=round(f, 5), diff_flow_pct=round((values[i][j] - f) / f * 100, 1),
                            hd_shipped_ns=h, diff_shipped_pct=round((values[i][j] - h) / h * 100, 1)))
    return out


def rows() -> list[dict]:
    out = []
    for name, short, function in PAIRS:
        folder = ROOT / "build/cells" / f"dd2_gc1__{name}"
        r = compare.compare(folder, folder.name, short)
        ours, hd = r["width_sites"]["ours"], r["width_sites"]["hd"]
        out.append(dict(
            function=function, cell=folder.name, hd=compare.PREFIX + short,
            sites_ours=ours, sites_hd=hd, extra_sites=ours - hd,
            area_ours_um2=round(ours * SITE * HEIGHT, 4), area_hd_um2=round(hd * SITE * HEIGHT, 4),
            frame="match" if r["frame"]["match"] else "differs", lvs_vs_hd=r["lvs_vs_hd"],
            met1_inside="no" if r["wiring"]["ours"]["met1_only_rails"] else "yes",
            breaks_ours=sum(r["gates"]["ours"]["diffusion_breaks"].values()),
            breaks_hd=sum(r["gates"]["hd"]["diffusion_breaks"].values()),
            **summary(timing_rows.setdefault(folder.name, timing(folder.name, short, function)))))
    return out


timing_rows: dict[str, list[dict]] = {}


def summary(t: list[dict]) -> dict:
    """The cell's slowest delay and slew, ours against HD, at the table point."""
    out = {}
    for label, kinds in (("delay", DELAYS), ("slew", SLEWS)):
        ours = max(r["ours_ns"] for r in t if r["value"] in kinds)
        flow = max(r["hd_flow_ns"] for r in t if r["value"] in kinds)
        shipped = max(r["hd_shipped_ns"] for r in t if r["value"] in kinds)
        out.update({f"{label}_ours_ns": ours, f"{label}_hd_ns": flow, f"{label}_diff_pct": round((ours - flow) / flow * 100, 1),
                    f"{label}_hd_shipped_ns": shipped})
    out["point"] = f"{t[0]['slew_ns']} ns / {t[0]['load_pf']} pF"
    return out


SIZINGS = [("hd", "dd2_gc1__nor3_1"), ("stack", "dd2_gc1__nor3_1_stack")]
SIZINGS_OUT = ROOT / "results/nor3_sizings.csv"
NOR3 = (("A", "B", "C"), "Y", "!(A | B | C)")


def schematic_point(sizing: str, pmos: str = "pfet_01v8_hvt") -> dict:
    """One sizing of nor3 characterized from its schematic (no layout parasitics, no SA/SB) at the table
    point, so the two sizings can be compared even where one cannot be drawn. pmos="pfet_01v8" swaps the
    high-Vt PMOS for the standard one, to measure what high Vt costs in rising delay (handout 8.3)."""
    from src.cell.build import stacked
    from src.cell.network import Cell, build_stage, schematic
    stage = build_stage(*NOR3)
    cell = Cell((stage,), stage)
    if sizing == "stack":
        cell = stacked(cell, 0.65, 1.0, lambda *a: None)
    name = f"dd2_gc1__nor3_1_{sizing}_schematic" + ("" if pmos == "pfet_01v8_hvt" else "_svt")
    folder = ROOT / "build/nor3_sizings" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.spice").write_text(schematic(cell.flat, name, 0.65, 1.0).replace("pfet_01v8_hvt", pmos))
    lib = read_cell("nor3_1").arcs[0].tables["cell_rise"]
    point = ([lib["index_1"][nearest(lib["index_1"], CAP_POINT[0])]], [lib["index_2"][nearest(lib["index_2"], CAP_POINT[1])]])
    t = characterize(folder, name, f"{name}.spice", list(NOR3[0]), NOR3[1], truth_table(NOR3[2], NOR3[0]),
                     {pin: point for pin in NOR3[0]}, read_setup())
    t["transistors"] = len(cell.flat.fets)
    return t


def nor3_sizings() -> list[dict]:
    """The two sizings of !(A | B | C) (handout 8.2): width, and per input pin the delay and slew at the
    table point nearest 100 ps / 10 fF and the input capacitance. Each sizing from its extracted layout
    where it was drawn, and from its schematic in any case (the like-for-like comparison). A sizing the
    generator refused has its width as the narrowest bound over its Euler orders (layout.min_width), the
    reason in the reason column."""
    from src.cell.build import stacked
    from src.cell.layout import min_width
    from src.cell.network import Cell, build_stage, euler_orders
    out = []
    for sizing, cell in SIZINGS:
        response = json.loads((ROOT / "cells" / cell / "response.json").read_text())
        drawn = response["status"] == "pass"
        if drawn:
            width = dict(sites=response["width_sites"], area_um2=response["area_um2"], width_is="drawn", reason="")
        else:
            stage = build_stage(*NOR3)
            c = stacked(Cell((stage,), stage), 0.65, 1.0, lambda *a: None) if sizing == "stack" else Cell((stage,), stage)
            bound = min(min_width(o) for o in euler_orders(c.flat))
            sites = -(-round(bound / SITE, 6) // 1)
            width = dict(sites=int(sites), area_um2=round(sites * SITE * HEIGHT, 4), width_is="at least (not drawn)",
                         reason=response.get("reason", ""))
        views = [("schematic", schematic_point(sizing)), ("schematic, standard-Vt PMOS", schematic_point(sizing, "pfet_01v8"))]
        if drawn:
            views.insert(0, ("extracted", json.loads((ROOT / "build/cells" / cell / f"{cell}_timing.json").read_text())))
        for view, t in views:
            for arc in t["arcs"]:
                i, j = nearest(arc["index_1"], CAP_POINT[0]), nearest(arc["index_2"], CAP_POINT[1])
                out.append(dict(sizing=sizing, cell=cell, view=view, **width,
                                transistors=t.get("transistors", response.get("transistors")), pin=arc["pin"],
                                slew_ns=arc["index_1"][i], load_pf=arc["index_2"][j],
                                capacitance_pf=round(t["pins"][arc["pin"]]["capacitance"], 6),
                                **{k: round(v[i][j], 5) for k, v in arc["tables"].items()}))
    return out


if __name__ == "__main__":
    sizings = nor3_sizings()
    with SIZINGS_OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(sizings[0]))
        w.writeheader()
        w.writerows(sizings)
    if "--sizings" in sys.argv:     # the two sizings of nor3 only
        print(f"-> {SIZINGS_OUT}")
        sys.exit(0)
    table = rows()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(table[0]))
        w.writeheader()
        w.writerows(table)
    with TIMING_OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(next(iter(timing_rows.values()))[0]))
        w.writeheader()
        for t in timing_rows.values():
            w.writerows(t)
    for row in table:
        print(f"{row['cell']:24s} {row['sites_ours']:>2} sites vs {row['sites_hd']:>2}  "
              f"area {row['area_ours_um2']:>7} vs {row['area_hd_um2']:>7} um2  lvs vs HD {row['lvs_vs_hd']:5s}  "
              f"met1 inside {row['met1_inside']:3s}  breaks {row['breaks_ours']} vs {row['breaks_hd']}  "
              f"delay {row['delay_ours_ns']} vs {row['delay_hd_ns']} ns ({row['delay_diff_pct']:+}%)  "
              f"slew {row['slew_ours_ns']} vs {row['slew_hd_ns']} ns ({row['slew_diff_pct']:+}%)")
    print(f"-> {OUT}, {TIMING_OUT}")
