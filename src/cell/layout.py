"""Draw a single-stage cell inside the HD frame of given/plan_hd.json.

Columns run left to right: diffusion, gate, diffusion, ... as in the Euler
order. Every wire is li1; met1 is only used for the rails.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path

import gdsfactory as gf

from src.cell.network import Order, Stage

ROOT = Path(__file__).resolve().parents[2]
PLAN = json.loads((ROOT / "given/plan_hd.json").read_text())
FRAME = PLAN["frame"]
SITE = FRAME["site"]["width"]
HEIGHT = FRAME["site"]["height"]
GRID = PLAN["grid"]

LAYER = dict(nwell=(64, 20), diff=(65, 20), poly=(66, 20), licon=(66, 44), li=(67, 20),
             mcon=(67, 44), met1=(68, 20), npc=(95, 20), nsdm=(93, 44), psdm=(94, 20),
             hvtp=(78, 44), areaid=(81, 4), boundary=(236, 0),
             li_label=(67, 5), li_pin=(67, 16), met1_label=(68, 5), met1_pin=(68, 16),
             nwell_label=(64, 5), nwell_pin=(64, 16), pwell_label=(64, 59), pwell_pin=(122, 16))

# Design rules (sky130A.tech, magic DRC deck)
L = 0.15            # poly.1a gate length
CUT = 0.17          # licon.1, mcon.1
CUT_GATE = 0.05     # licon.11 diffusion contact to standard cell gate
CUT_DIFF = 0.04     # licon.5a diffusion overlap of contact
CUT_PITCH = 0.34    # licon.2 contact spacing 0.17
POLY_SPACE = 0.21   # poly.2
POLY_CUT = 0.05     # licon.8 poly overlap of poly contact
POLY_CUT_DIR = 0.08 # licon.8a ... in one direction
ENDCAP = 0.13       # poly.8
DIFF_SPACE = 0.27   # diff/tap.3
LI = 0.17           # li.1
LI_SPACE = 0.17     # li.3
LI_CUT_DIR = 0.08   # li.5 li overlap of contact in one direction
NPC_CUT = 0.10      # npc enclosure of poly contact

# Vertical plan (y, um). Rows and sizes from plan_hd.json "reference"
N_DIFF = (0.235, 0.885)
P_DIFF = (1.485, 2.485)
NPC = tuple(FRAME["npc_band"]["y"])
PAD_CUT = (NPC[0] + NPC_CUT, NPC[0] + NPC_CUT + CUT)           # 1.075 .. 1.245
PAD_LI = (PAD_CUT[0], 1.315)                                   # li.6 area, as in HD
PAD_POLY = (PAD_CUT[0] - POLY_CUT_DIR, PAD_CUT[1] + POLY_CUT_DIR)
VGND_LI_TOP = FRAME["rails"]["VGND"]["li1"]["y"][1]            # 0.085
VPWR_LI_BOT = FRAME["rails"]["VPWR"]["li1"]["y"][0]            # 2.635
N_LI = (VGND_LI_TOP + LI_SPACE, PAD_LI[0] - LI_SPACE)          # 0.255 .. 0.905
P_LI = (PAD_LI[1] + LI_SPACE, VPWR_LI_BOT - LI_SPACE)          # 1.485 .. 2.465
POLY_Y = (N_DIFF[0] - ENDCAP, P_DIFF[1] + ENDCAP)

PAD_HALF = CUT / 2 + LI_CUT_DIR          # half width of an input pad on li
STRIP_HALF = LI / 2                      # half width of a narrow li strip
WIDE_HALF = CUT / 2 + LI_CUT_DIR         # li strip over contacts that does not reach a rail


def snap(v: float) -> float:
    return round(round(v / GRID) * GRID, 4)


def contacts_y(row):
    """Contact centres in one column: NMOS from the top down, PMOS from the bottom up,
    so the narrow supply strips keep their li.5 overlap."""
    if row == "n":
        top, bottom = min(N_DIFF[1] - CUT_DIFF, N_LI[1] - LI_CUT_DIR), N_DIFF[0] + CUT_DIFF
        n = math.floor((top - bottom - CUT) / CUT_PITCH + 1e-9) + 1
        return [snap(top - CUT / 2 - i * CUT_PITCH) for i in range(n)][::-1]
    bottom, top = max(P_DIFF[0] + CUT_DIFF, P_LI[0] + LI_CUT_DIR), P_DIFF[1] - CUT_DIFF
    n = math.floor((top - bottom - CUT) / CUT_PITCH + 1e-9) + 1
    return [snap(bottom + CUT / 2 + i * CUT_PITCH) for i in range(n)]


@dataclass
class Plan:
    width: float = 0
    gate_x: list = field(default_factory=list)
    col_x: list = field(default_factory=list)
    pad_x: dict = field(default_factory=dict)
    crossing: dict = field(default_factory=dict)
    diff_x: tuple = (0, 0)


def is_internal(net):
    return net[0] in "np" and net[1:].isdigit()


def contacted(order: Order):
    """Per row, the set of columns that need a contact."""
    out = []
    for nodes in (order.n_nodes, order.p_nodes):
        out.append({i for i, net in enumerate(nodes) if not (is_internal(net) and nodes.count(net) == 1)})
    return out


def place(stage: Stage, order: Order) -> Plan:
    n_cont, p_cont = contacted(order)
    either = n_cont | p_cont
    cols = len(order.gates) + 1

    # x of every column and gate, with the left diffusion edge at 0
    col_x, gate_x = [CUT_DIFF + CUT / 2], []
    for i in range(1, cols):
        if i - 1 in either:
            left = col_x[-1] + CUT / 2 + CUT_GATE
        else:
            left = gate_x[-1] + L / 2 + POLY_SPACE
        gate_x.append(left + L / 2)
        right = left + L
        col_x.append(right + CUT_GATE + CUT / 2 if i in either else right + POLY_SPACE / 2)
    diff_right = col_x[-1] + CUT / 2 + CUT_DIFF

    crossing = route_crossings(stage, order, col_x, n_cont, p_cont)
    pads = place_pads(order, gate_x, list(crossing.values()))

    poly = [g - L / 2 for g in gate_x] + [p - CUT / 2 - POLY_CUT for p in pads.values()]
    poly_r = [g + L / 2 for g in gate_x] + [p + CUT / 2 + POLY_CUT for p in pads.values()]
    li = [x - WIDE_HALF for x in col_x] + [p - PAD_HALF for p in pads.values()]
    li_r = [x + WIDE_HALF for x in col_x] + [p + PAD_HALF for p in pads.values()]
    shift = max(DIFF_SPACE / 2, POLY_SPACE / 2 - min(poly), LI_SPACE / 2 - min(li))
    need = max(diff_right + DIFF_SPACE / 2, max(poly_r) + POLY_SPACE / 2, max(li_r) + LI_SPACE / 2) + shift
    width = snap(math.ceil(need / SITE - 1e-9) * SITE)
    shift = snap(shift + (width - need) / 2)

    plan = Plan(width=width, diff_x=(shift, snap(shift + diff_right)))
    plan.col_x = [snap(x + shift) for x in col_x]
    plan.gate_x = [snap(g + shift) for g in gate_x]
    plan.pad_x = {k: snap(v + shift) for k, v in pads.items()}
    plan.crossing = {k: snap(v + shift) for k, v in crossing.items()}
    return plan


def route_crossings(stage, order, col_x, n_cont, p_cont):
    """For each net in both rows, the column where its li crosses the npc band."""
    out = {}
    for net in sorted(set(order.n_nodes) & set(order.p_nodes) - {"VGND", "VPWR"}):
        n_cols = [i for i, v in enumerate(order.n_nodes) if v == net and i in n_cont]
        p_cols = [i for i, v in enumerate(order.p_nodes) if v == net and i in p_cont]
        best = None
        for c in range(len(col_x)):
            spans = [(min(n_cols + [c]), max(n_cols + [c]), order.n_nodes, n_cont),
                     (min(p_cols + [c]), max(p_cols + [c]), order.p_nodes, p_cont)]
            if any(nodes[k] != net and k in cont for lo, hi, nodes, cont in spans for k in range(lo, hi + 1)):
                continue
            cost = sum(hi - lo for lo, hi, *_ in spans)
            if best is None or cost < best[0]:
                best = (cost, c)
        if best is None:
            raise ValueError(f"cannot route {net} between the rows on li")
        out[net] = col_x[best[1]]
    return out


def place_pads(order, gate_x, crossings):
    """x of each input's poly contact: as close to its gate as the li and poly spacing allow."""
    pads = {}
    for i, (gate, g) in enumerate(zip(order.gates, gate_x)):
        if gate in pads:
            continue
        for off in sorted({0, 0.19, -0.19, 0.1, -0.1, 0.21, -0.21}, key=lambda o: (abs(o), o)):
            p = g + off
            if any(abs(p - c) < PAD_HALF + LI_SPACE + STRIP_HALF - 1e-9 for c in crossings):
                continue
            if any(abs(p - q) < 2 * PAD_HALF + LI_SPACE - 1e-9 for q in pads.values()):
                continue
            if any(j != i and abs(p - x) < CUT / 2 + POLY_CUT + POLY_SPACE + L / 2 - 1e-9
                   for j, x in enumerate(gate_x) if order.gates[j] != gate):
                continue
            pads[gate] = p
            break
        else:
            raise ValueError(f"no room for the {gate} contact")
    return pads


def rect(c, layer, x0, y0, x1, y1):
    x0, y0, x1, y1 = map(snap, (x0, y0, x1, y1))
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"empty rectangle on {layer}: {(x0, y0, x1, y1)}")
    c.add_polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layer=LAYER[layer])


def box(c, layer, x, y, w, h):
    rect(c, layer, x - w / 2, y - h / 2, x + w / 2, y + h / 2)


def draw(name: str, stage: Stage, order: Order, wn: float = 0.65, wp: float = 1.0):
    gf.gpdk.PDK.activate()
    assert abs((N_DIFF[1] - N_DIFF[0]) - wn) < 1e-9 and abs((P_DIFF[1] - P_DIFF[0]) - wp) < 1e-9, \
        "only HD x1 sizes for now"
    plan = place(stage, order)
    w = plan.width
    c = gf.Component(name)

    # frame
    for key in ("nwell", "nsdm", "psdm", "hvtp"):
        lo, hi = FRAME[key]["x"]
        rect(c, key, lo, FRAME[key]["y"][0], w + 0.19 if hi == "width + 0.19" else w, FRAME[key]["y"][1])
    rect(c, "npc", 0, NPC[0], w, NPC[1])
    rect(c, "areaid", 0, 0, w, HEIGHT)
    rect(c, "boundary", 0, 0, w, HEIGHT)
    for rail in ("VGND", "VPWR"):
        r = FRAME["rails"][rail]
        rect(c, "met1", 0, r["met1"]["y"][0], w, r["met1"]["y"][1])
        rect(c, "li", 0, r["li1"]["y"][0], w, r["li1"]["y"][1])
        for k in range(round(w / SITE)):
            box(c, "mcon", 0.23 + SITE * k, sum(r["mcon"]["y"]) / 2, CUT, CUT)

    # diffusion and gates
    x0, x1 = plan.diff_x
    rect(c, "diff", x0, N_DIFF[0], x1, N_DIFF[1])
    rect(c, "diff", x0, P_DIFF[0], x1, P_DIFF[1])
    for g in plan.gate_x:
        rect(c, "poly", g - L / 2, POLY_Y[0], g + L / 2, POLY_Y[1])

    # input contacts
    pins = {}
    for i, gate in enumerate(order.gates):
        g, p = plan.gate_x[i], plan.pad_x[gate]
        if order.gates.index(gate) != i:
            continue
        box(c, "licon", p, sum(PAD_CUT) / 2, CUT, CUT)
        rect(c, "poly", min(p - CUT / 2 - POLY_CUT, g - L / 2), PAD_POLY[0],
             max(p + CUT / 2 + POLY_CUT, g + L / 2), PAD_POLY[1])
        rect(c, "li", p - PAD_HALF, PAD_LI[0], p + PAD_HALF, PAD_LI[1])
        pins[gate] = (p - PAD_HALF + 0.04, PAD_LI[1] - 0.04 - CUT)

    # diffusion contacts and li
    n_cont, p_cont = contacted(order)
    rows = [(order.n_nodes, n_cont, N_DIFF, N_LI, "VGND"), (order.p_nodes, p_cont, P_DIFF, P_LI, "VPWR")]
    for nodes, cont, diff, li, rail in rows:
        ys = contacts_y("n" if rail == "VGND" else "p")
        for i in sorted(cont):
            x = plan.col_x[i]
            for y in ys:
                box(c, "licon", x, y, CUT, CUT)
            if nodes[i] == rail:
                if rail == "VGND":
                    lo, hi = -VGND_LI_TOP, ys[-1] + CUT / 2 + LI_CUT_DIR
                else:
                    lo, hi = ys[0] - CUT / 2 - LI_CUT_DIR, HEIGHT + VGND_LI_TOP
                rect(c, "li", x - STRIP_HALF, lo, x + STRIP_HALF, hi)
        # nets with more than one contact in this row, or that cross to the other row
        for net in sorted(set(nodes) - {rail}):
            xs = [plan.col_x[i] for i in cont if nodes[i] == net]
            if net in plan.crossing:
                xs.append(plan.crossing[net])
            if not xs:
                continue
            rect(c, "li", min(xs) - WIDE_HALF, li[0], max(xs) + WIDE_HALF, li[1])

    for net, x in plan.crossing.items():
        rect(c, "li", x - STRIP_HALF, N_LI[1] - 0.01, x + STRIP_HALF, P_LI[0] + 0.01)
        pins[net] = (x - WIDE_HALF + 0.04, P_LI[0] + 0.04)

    # pins and labels
    # pin boxes start on bare li, not on a contact, so extresist finds the wire
    for net, (x, y) in pins.items():
        rect(c, "li_pin", x, y, x + CUT, y + CUT)
        c.add_label(net, position=(snap(x + CUT / 2), snap(y + CUT / 2)), layer=LAYER["li_label"])
    for rail, y in (("VGND", 0.0), ("VPWR", HEIGHT)):
        box(c, "met1_pin", 0.23, y, CUT, CUT)
        c.add_label(rail, position=(0.23, y), layer=LAYER["met1_label"])
    box(c, "nwell_pin", 0.23, HEIGHT, CUT, CUT)
    c.add_label("VPB", position=(0.23, HEIGHT), layer=LAYER["nwell_label"])
    box(c, "pwell_pin", 0.23, 0.0, CUT, CUT)
    c.add_label("VNB", position=(0.23, 0.0), layer=LAYER["pwell_label"])

    meta = dict(name=name, width=w, width_sites=round(w / SITE), gate_x=plan.gate_x, col_x=plan.col_x,
                pad_x=plan.pad_x, gates=list(order.gates), n_nodes=list(order.n_nodes),
                p_nodes=list(order.p_nodes))
    return c, meta
