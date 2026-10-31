"""Draw a single-stage cell inside the HD frame of given/plan_hd.json.

Columns run left to right: diffusion, gate, diffusion, ... as in the Euler
order. Every wire is li1; met1 is only used for the rails.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from itertools import islice, product
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
CUT_DIFF_DIR = 0.06 # licon.5c diffusion overlap of contact in one direction
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
LANE_Y = {"n": (N_LI[1] - LI, N_LI[1]), "p": (P_LI[0], P_LI[0] + LI)}   # li lane on the row's inner edge
OUTER_Y = {"n": (N_LI[0], N_LI[0] + LI), "p": (P_LI[1] - LI, P_LI[1])}  # li lane on the row's outer edge, by the rail
ROWS = {"n": ("VGND", N_DIFF, N_LI), "p": ("VPWR", P_DIFF, P_LI)}
WIDEN_STEPS = tuple(round(0.06 * k, 2) for k in range(8))   # extra width (um) tried for a column between two gates
MAX_WIDENINGS, MAX_CROSSINGS = 300, 60
CROSSING_SHIFTS = tuple(sorted({round(s * 0.03 * k, 2) for k in range(8) for s in (1, -1)}, key=lambda d: (abs(d), d)))   # crossing off a gate (um)
PAD_REACH = 0.40    # farthest a poly contact sits from its gate


def snap(v: float) -> float:
    return round(round(v / GRID) * GRID, 4)


def contacts_y(row, w=None, lo=-math.inf, hi=math.inf):
    """Contact centres in one column of diffusion w wide, kept between lo and hi: NMOS from the
    top down, PMOS from the bottom up, so the narrow supply strips keep their li.5 overlap.
    A narrower NMOS keeps its bottom edge and a narrower PMOS its top edge, next to the rails.
    The end columns have only licon.5a's overlap beside the contacts, so above and below them the
    diffusion keeps licon.5c's; in a full-width row the li overlap already leaves that much."""
    if row == "n":
        w = N_DIFF[1] - N_DIFF[0] if w is None else w
        top = min(N_DIFF[0] + w - CUT_DIFF_DIR, N_LI[1] - LI_CUT_DIR, hi)
        bottom = max(N_DIFF[0] + CUT_DIFF_DIR, lo)
        n = math.floor((top - bottom - CUT) / CUT_PITCH + 1e-9) + 1
        return [snap(top - CUT / 2 - i * CUT_PITCH) for i in range(n)][::-1]
    w = P_DIFF[1] - P_DIFF[0] if w is None else w
    bottom, top = max(P_DIFF[1] - w + CUT_DIFF_DIR, P_LI[0] + LI_CUT_DIR, lo), min(P_DIFF[1] - CUT_DIFF_DIR, hi)
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
    diff_w: dict = field(default_factory=dict)    # row -> diffusion width under each gate
    cont: dict = field(default_factory=dict)      # row -> contacted columns
    half: dict = field(default_factory=dict)      # (row, column) -> half width of its li strip
    ys: dict = field(default_factory=dict)        # (row, column) -> contact centres
    lanes: dict = field(default_factory=dict)     # row -> [(net, x0, x1, "inner" | "outer")] li along an edge

    def half_at(self, row, x):
        for j in self.cont[row]:
            if abs(self.col_x[j] - x) < 1e-6:
                return self.half[(row, j)]
        return WIDE_HALF

    def band(self, row, x0, x1, net):
        """y extent of net's li between x0 and x1: the row's li band, less any outer lane of
        another net that passes within li spacing."""
        lo, hi = ROWS[row][2]
        for other, a, b, edge in self.lanes[row]:
            if edge == "outer" and other != net and a < x1 + LI_SPACE - 1e-9 and b > x0 - LI_SPACE + 1e-9:
                if row == "n":
                    lo = OUTER_Y["n"][1] + LI_SPACE
                else:
                    hi = OUTER_Y["p"][0] - LI_SPACE
        return lo, hi


def is_internal(net):
    return net[0] in "np" and net[1:].isdigit()


def contacted(order: Order):
    """Per row, the set of columns that need a contact."""
    out = []
    for nodes in (order.n_nodes, order.p_nodes):
        out.append({i for i, net in enumerate(nodes) if not (is_internal(net) and nodes.count(net) == 1)})
    return out


def place(stage: Stage, order: Order, wn: float = 0.65, wp: float = 1.0, widths: dict | None = None) -> Plan:
    """Raises ValueError when this order cannot be drawn; the caller tries the next one."""
    widths = widths or {}
    diff_w = {"n": [widths.get(("n", g), wn) for g in order.gates],
              "p": [widths.get(("p", g), wp) for g in order.gates]}
    for row, ws in diff_w.items():
        band = ROWS[row][1]
        if max(ws) > band[1] - band[0] + 1e-9:
            raise ValueError(f"a {row}MOS {max(ws)} um wide does not fit the row (folding is not built yet)")

    n_cont, p_cont = contacted(order)
    either = n_cont | p_cont
    cols = len(order.gates) + 1

    # Try the cheapest crossings first; if no crossing leaves room for every input's poly contact,
    # widen the columns between gates a step at a time, as HD's nand3_1 and o21ai_1 do.
    inner = list(range(1, cols - 1))
    widenings = sorted(product(WIDEN_STEPS, repeat=len(inner)), key=lambda e: (sum(e), max(e, default=0), e))
    error = ValueError("no crossing leaves room for the poly contacts")
    for extra in widenings[:MAX_WIDENINGS]:
        col_x, gate_x = columns(cols, either, dict(zip(inner, extra)))
        options = route_crossings(stage, order, col_x, gate_x, n_cont, p_cont)
        for choice in islice(product(*options.values()), MAX_CROSSINGS):
            crossing = dict(zip(options, choice))
            try:
                pads = place_pads(order, gate_x, list(crossing.values()))
                return finish(order, col_x, gate_x, crossing, pads, diff_w, n_cont, p_cont)
            except ValueError as e:
                error = e
    raise error


def columns(cols: int, either: set, extra: dict):
    """x of every column and gate, with the left diffusion edge at 0. extra[i] widens column i."""
    col_x, gate_x = [CUT_DIFF + CUT / 2], []
    for i in range(1, cols):
        if i - 1 in either:
            left = col_x[-1] + CUT / 2 + CUT_GATE + extra.get(i - 1, 0) / 2
        else:
            left = gate_x[-1] + L / 2 + POLY_SPACE + extra.get(i - 1, 0)
        gate_x.append(left + L / 2)
        right = left + L
        col_x.append(right + CUT_GATE + CUT / 2 + extra.get(i, 0) / 2 if i in either else right + POLY_SPACE / 2)
    return col_x, gate_x


def finish(order, col_x, gate_x, crossing, pads, diff_w, n_cont, p_cont) -> Plan:
    """Cell width, centring, and the li of each row."""
    diff_right = col_x[-1] + CUT / 2 + CUT_DIFF
    poly = [g - L / 2 for g in gate_x] + [p - CUT / 2 - POLY_CUT for p in pads.values()]
    poly_r = [g + L / 2 for g in gate_x] + [p + CUT / 2 + POLY_CUT for p in pads.values()]
    li = [x - WIDE_HALF for x in col_x] + [p - PAD_HALF for p in pads.values()]
    li_r = [x + WIDE_HALF for x in col_x] + [p + PAD_HALF for p in pads.values()]
    shift = max(DIFF_SPACE / 2, POLY_SPACE / 2 - min(poly), LI_SPACE / 2 - min(li))
    need = max(diff_right + DIFF_SPACE / 2, max(poly_r) + POLY_SPACE / 2, max(li_r) + LI_SPACE / 2) + shift
    width = snap(math.ceil(need / SITE - 1e-9) * SITE)
    shift = snap(shift + (width - need) / 2)

    plan = Plan(width=width, diff_x=(shift, snap(shift + diff_right)), diff_w=diff_w,
                cont={"n": n_cont, "p": p_cont}, lanes={"n": [], "p": []})
    plan.col_x = [snap(x + shift) for x in col_x]
    plan.gate_x = [snap(g + shift) for g in gate_x]
    plan.pad_x = {k: snap(v + shift) for k, v in pads.items()}
    plan.crossing = {k: snap(v + shift) for k, v in crossing.items()}
    for row, nodes in (("n", order.n_nodes), ("p", order.p_nodes)):
        plan_row(plan, row, nodes)
    check_lanes(plan)
    return plan


def plan_row(plan: Plan, row: str, nodes):
    """li strip widths, lanes and contacts of one row.

    A strip next to a contact of another signal net is narrow, as in HD, and its contacts keep the
    li.5 overlap at both ends. A net whose contacts lie on both sides of a rail contact joins them
    with a lane along the row's inner edge, and the rail column's contacts move away from the lane
    (HD's nand3_1, a21oi_1 and o21ai_1 do the same). Where it must pass another signal net's
    contact instead, the lane runs along the outer edge, by the rail, and that contact moves inward:
    a rail strip reaches the outer edge and a signal strip the inner one, so each edge can pass
    only one kind. Each stretch between two of the net's contacts picks its own edge."""
    rail, band, li = ROWS[row]
    cont = plan.cont[row]
    for j in cont:
        crowded = [k for k in (j - 1, j + 1) if k in cont and nodes[k] not in (rail, nodes[j])]
        plan.half[(row, j)] = STRIP_HALF if nodes[j] == rail or crowded else WIDE_HALF

    def near(x0, x1, net):
        """Contacted columns of other nets whose li strip comes within li spacing of x0..x1."""
        return [k for k in cont if nodes[k] != net and plan.col_x[k] - plan.half[(row, k)] < x1 + LI_SPACE - 1e-9
                and plan.col_x[k] + plan.half[(row, k)] > x0 - LI_SPACE + 1e-9]

    moved = set()
    for net in sorted(set(nodes) - {rail}):
        xs = [plan.col_x[j] for j in cont if nodes[j] == net]
        if net in plan.crossing:
            xs.append(plan.crossing[net])
        if len(xs) < 2:
            continue
        lo, hi = min(xs), max(xs)
        if not near(lo - plan.half_at(row, lo), hi + plan.half_at(row, hi), net):
            continue
        # a lane: full strips on the net's own columns, joined along an edge; each stretch between
        # two of the net's positions takes the inner edge past rails, the outer edge past signals
        left = lambda x: snap(x - (plan.half_at(row, x) if x in plan.col_x else STRIP_HALF))
        right = lambda x: snap(x + (plan.half_at(row, x) if x in plan.col_x else STRIP_HALF))
        stretches = []
        for a, b in zip(sorted(xs), sorted(xs)[1:]):
            passed = near(left(a), right(b), net)
            signals = sorted({nodes[k] for k in passed} - {rail})
            if signals and len(signals) < len({nodes[k] for k in passed}):
                raise ValueError(f"{net} cannot pass {', '.join(signals)} and {rail} at once in the {row} row on li")
            edge = "outer" if signals else "inner"
            if stretches and stretches[-1][0] == edge:
                stretches[-1][2] = right(b)
                stretches[-1][3] |= set(passed)
            else:
                stretches.append([edge, left(a), right(b), set(passed)])
        for edge, x0, x1, passed in stretches:
            plan.lanes[row].append((net, x0, x1, edge))
            if edge == "inner":
                moved |= passed

    # an outer lane may pass only strips that stop short of the outer edge
    for net, x0, x1, edge in plan.lanes[row]:
        if edge != "outer":
            continue
        for k in near(x0, x1, net):
            if any(other == nodes[k] and e == "outer" for other, *_, e in plan.lanes[row]):
                raise ValueError(f"the outer lanes of {net} and {nodes[k]} meet in the {row} row")

    # Under another net's outer lane a narrow strip, which covers its contact by li.5 above and
    # below, leaves no room for the contact in the NMOS row. Widen it where the neighbours allow:
    # li.5 holds on two opposite sides, so a wide strip covers the contact sideways instead.
    for j in cont:
        x = plan.col_x[j]
        if nodes[j] == rail or plan.half[(row, j)] != STRIP_HALF or plan.band(row, x - STRIP_HALF, x + STRIP_HALF, nodes[j]) == li:
            continue
        others = [(plan.col_x[k], plan.half[(row, k)]) for k in cont if nodes[k] != nodes[j]]
        others += [(cx, STRIP_HALF) for net, cx in plan.crossing.items() if net != nodes[j]]
        if all(abs(x - ox) >= WIDE_HALF + oh + LI_SPACE - 1e-9 for ox, oh in others):
            plan.half[(row, j)] = WIDE_HALF

    lane = LANE_Y[row]
    for j in cont:
        ws = [plan.diff_w[row][g] for g in (j - 1, j) if 0 <= g < len(plan.gate_x)]
        lo, hi = -math.inf, math.inf
        if j in moved and row == "n":
            hi = lane[0] - LI_SPACE - LI_CUT_DIR
        elif j in moved:
            lo = lane[1] + LI_SPACE + LI_CUT_DIR
        elif nodes[j] != rail and plan.half[(row, j)] == STRIP_HALF:
            lo, hi = li[0] + LI_CUT_DIR, li[1] - LI_CUT_DIR
        x = plan.col_x[j]
        band = plan.band(row, x - plan.half[(row, j)], x + plan.half[(row, j)], nodes[j])
        if nodes[j] != rail and band != li:     # under another net's outer lane: the strip and its contacts move inward
            ends = LI_CUT_DIR if plan.half[(row, j)] == STRIP_HALF else 0     # a wide strip meets li.5 sideways
            lo, hi = max(lo, band[0] + ends), min(hi, band[1] - ends)
        ys = contacts_y(row, min(ws), lo, hi)
        if not ys:
            raise ValueError(f"no room for a contact in column {j} of the {row} row")
        plan.ys[(row, j)] = ys


def check_lanes(plan: Plan):
    """Lanes on the same edge must keep li spacing from each other, and inner lanes from the other
    nets' crossings."""
    for row, lanes in plan.lanes.items():
        for i, (net, x0, x1, edge) in enumerate(lanes):
            for other, y0, y1, e in lanes[i + 1:]:
                if e == edge and other != net and x0 < y1 + LI_SPACE and y0 < x1 + LI_SPACE:
                    raise ValueError(f"the lanes of {net} and {other} meet in the {row} row")
            if edge == "outer":
                continue
            for other, x in plan.crossing.items():
                if other != net and x0 - LI_SPACE < x + STRIP_HALF and x - STRIP_HALF < x1 + LI_SPACE:
                    raise ValueError(f"{other} crosses the lane of {net} in the {row} row")


def route_crossings(stage, order, col_x, gate_x, n_cont, p_cont) -> dict:
    """For each net in both rows, the x where its li may cross the npc band, best first: on a column
    or over a gate, as HD's nand3_1 does. The net's li in each row reaches from its contacts to the
    crossing, so no other net's contact may lie in between; a rail contact only with a lane (plan_row).
    Positions count in half columns: 2k is column k, 2k + 1 the gate after it."""
    out = {}
    for net in sorted(set(order.n_nodes) & set(order.p_nodes) - {"VGND", "VPWR"}):
        n_cols = [2 * i for i, v in enumerate(order.n_nodes) if v == net and i in n_cont]
        p_cols = [2 * i for i, v in enumerate(order.p_nodes) if v == net and i in p_cont]
        options = []
        for h in range(2 * len(col_x) - 1):
            spans = [(min(n_cols + [h]), max(n_cols + [h]), order.n_nodes, n_cont, "VGND"),
                     (min(p_cols + [h]), max(p_cols + [h]), order.p_nodes, p_cont, "VPWR")]
            jumps, ok = 0, True
            for lo, hi, nodes, cont, rail in spans:
                for k in range((lo + 1) // 2, hi // 2 + 1):
                    if nodes[k] == net or k not in cont:
                        continue
                    if nodes[k] == rail and 2 * k != h:
                        jumps += 1
                    else:
                        ok = False
            if not ok:
                continue
            cost = (jumps, sum(hi - lo for lo, hi, *_ in spans), h % 2)
            if h % 2 == 0:
                options.append((cost + (0, h), col_x[h // 2]))
                continue
            left, right = col_x[h // 2], col_x[h // 2 + 1]
            for d in CROSSING_SHIFTS:
                x = gate_x[h // 2] + d
                if left + STRIP_HALF < x < right - STRIP_HALF:
                    options.append((cost + (abs(d), h), x))
        if not options:
            raise ValueError(f"cannot route {net} between the rows on li")
        out[net] = [x for _, x in sorted(options)]
    return out


def place_pads(order, gate_x, crossings):
    """x of each input's poly contact, left to right: the point nearest its gate (left first on a tie)
    that keeps li spacing to the crossings and the pads already placed, and poly spacing to the other
    gates. A pad up to PAD_REACH from its gate is joined to it by a poly stub."""
    pads = {}
    for i, (gate, g) in enumerate(zip(order.gates, gate_x)):
        if gate in pads:
            continue
        keep_out = [(c, PAD_HALF + LI_SPACE + STRIP_HALF) for c in crossings]
        keep_out += [(q, 2 * PAD_HALF + LI_SPACE) for q in pads.values()]
        keep_out += [(x, CUT / 2 + POLY_CUT + POLY_SPACE + L / 2)
                     for j, x in enumerate(gate_x) if order.gates[j] != gate]
        candidates = {g} | {x + s * d for x, d in keep_out for s in (1, -1)}
        fits = [p for p in map(snap, candidates)
                if abs(p - g) <= PAD_REACH + 1e-9 and all(abs(p - x) >= d - 1e-9 for x, d in keep_out)]
        if not fits:
            raise ValueError(f"no room for the {gate} contact")
        pads[gate] = min(fits, key=lambda p: (abs(p - g), p))
    return pads


def rect(c, layer, x0, y0, x1, y1):
    x0, y0, x1, y1 = map(snap, (x0, y0, x1, y1))
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"empty rectangle on {layer}: {(x0, y0, x1, y1)}")
    c.add_polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layer=LAYER[layer])


def box(c, layer, x, y, w, h):
    rect(c, layer, x - w / 2, y - h / 2, x + w / 2, y + h / 2)


def diffusion(c, plan: Plan, row: str):
    """One diffusion strip per row. Where the width under two gates differs, the edge away from
    the rail steps at the column between them, as in HD's o21ai_1."""
    x0, x1 = plan.diff_x
    runs = []
    for i, w in enumerate(plan.diff_w[row]):
        xa = x0 if i == 0 else plan.col_x[i]
        xb = x1 if i == len(plan.gate_x) - 1 else plan.col_x[i + 1]
        if runs and abs(runs[-1][2] - w) < 1e-9:
            runs[-1][1] = xb
        else:
            runs.append([xa, xb, w])
    edge, sign = (N_DIFF[0], 1) if row == "n" else (P_DIFF[1], -1)
    if len(runs) == 1:
        rect(c, "diff", x0, min(edge, edge + sign * runs[0][2]), x1, max(edge, edge + sign * runs[0][2]))
        return
    points = [(x0, edge), (x1, edge)]
    for xa, xb, w in reversed(runs):
        points += [(xb, edge + sign * w), (xa, edge + sign * w)]
    c.add_polygon([(snap(x), snap(y)) for x, y in points], layer=LAYER["diff"])


def draw(name: str, stage: Stage, order: Order, wn: float = 0.65, wp: float = 1.0, widths: dict | None = None):
    gf.gpdk.PDK.activate()
    plan = place(stage, order, wn, wp, widths)
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
    diffusion(c, plan, "n")
    diffusion(c, plan, "p")
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
    rows = [("n", order.n_nodes, N_LI, "VGND"), ("p", order.p_nodes, P_LI, "VPWR")]
    for row, nodes, li, rail in rows:
        cont = plan.cont[row]
        for i in sorted(cont):
            x, ys = plan.col_x[i], plan.ys[(row, i)]
            for y in ys:
                box(c, "licon", x, y, CUT, CUT)
            if nodes[i] == rail:
                if rail == "VGND":
                    lo, hi = -VGND_LI_TOP, ys[-1] + CUT / 2 + LI_CUT_DIR
                else:
                    lo, hi = ys[0] - CUT / 2 - LI_CUT_DIR, HEIGHT + VGND_LI_TOP
                rect(c, "li", x - STRIP_HALF, lo, x + STRIP_HALF, hi)
        # nets with more than one contact in this row, or that cross to the other row
        laned = {net for net, *_ in plan.lanes[row]}
        for net in sorted(set(nodes) - {rail}):
            xs = [plan.col_x[i] for i in cont if nodes[i] == net]
            if net in laned:
                for x in xs:
                    x0, x1 = x - plan.half_at(row, x), x + plan.half_at(row, x)
                    y0, y1 = plan.band(row, x0, x1, net)
                    rect(c, "li", x0, y0, x1, y1)
                continue
            if net in plan.crossing:
                xs.append(plan.crossing[net])
            if not xs:
                continue
            x0, x1 = min(xs) - plan.half_at(row, min(xs)), max(xs) + plan.half_at(row, max(xs))
            y0, y1 = plan.band(row, x0, x1, net)
            rect(c, "li", x0, y0, x1, y1)
        for net, x0, x1, edge in plan.lanes[row]:
            y0, y1 = (LANE_Y if edge == "inner" else OUTER_Y)[row]
            rect(c, "li", x0, y0, x1, y1)

    p_laned = {net for net, *_ in plan.lanes["p"]}
    for net, x in plan.crossing.items():
        rect(c, "li", x - STRIP_HALF, N_LI[1] - 0.01, x + STRIP_HALF, P_LI[0] + 0.01)
        half = plan.half_at("p", x)
        on_column = net not in p_laned or any(abs(plan.col_x[j] - x) < 1e-6 for j in plan.cont["p"])
        if on_column and half > STRIP_HALF:
            pins[net] = (x - half + 0.04, P_LI[0] + 0.04)
        else:   # a strip as wide as the pin: on the column, or on the crossing below the row
            pins[net] = (x - STRIP_HALF, P_LI[0] + 0.04 if on_column else P_LI[0] - 0.04 - CUT, "narrow")

    # pins and labels
    # pin boxes start on bare li, not on a contact, so extresist finds the wire
    # a pin as wide as its strip shrinks to Magic's 0.01 um grid, so Magic cannot round it off the wire
    for net, (x, y, *narrow) in pins.items():
        x0, x1 = (math.ceil(x * 100 - 1e-6) / 100, math.floor((x + CUT) * 100 + 1e-6) / 100) if narrow else (x, x + CUT)
        rect(c, "li_pin", x0, y, x1, y + CUT)
        c.add_label(net, position=(snap((x0 + x1) / 2), snap(y + CUT / 2)), layer=LAYER["li_label"])
    for rail, y in (("VGND", 0.0), ("VPWR", HEIGHT)):
        box(c, "met1_pin", 0.23, y, CUT, CUT)
        c.add_label(rail, position=(0.23, y), layer=LAYER["met1_label"])
    box(c, "nwell_pin", 0.23, HEIGHT, CUT, CUT)
    c.add_label("VPB", position=(0.23, HEIGHT), layer=LAYER["nwell_label"])
    box(c, "pwell_pin", 0.23, 0.0, CUT, CUT)
    c.add_label("VNB", position=(0.23, 0.0), layer=LAYER["pwell_label"])

    meta = dict(name=name, width=w, width_sites=round(w / SITE), gate_x=plan.gate_x, col_x=plan.col_x,
                pad_x=plan.pad_x, gates=list(order.gates), n_nodes=list(order.n_nodes),
                p_nodes=list(order.p_nodes), diff_w=plan.diff_w, lanes=plan.lanes)
    return c, meta
