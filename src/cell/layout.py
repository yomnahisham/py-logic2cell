"""Draw a single-stage cell inside the HD frame of given/plan_hd.json.

Columns run left to right: diffusion, gate, diffusion, ... as in the Euler
order. Every wire is li1; met1 is only used for the rails.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from itertools import combinations, islice, product
from pathlib import Path

import gdsfactory as gf

from src.cell import band as midband
from src.cell.network import BREAK, Order, Stage

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
MCON = 0.17         # mcon.1
MCON_SPACE = 0.19   # mcon.2
M1 = 0.14           # met1.1
M1_SPACE = 0.14     # met1.2
M1_CUT = 0.03       # met1.4 met1 overlap of mcon
M1_CUT_DIR = 0.06   # met1.5 ... in one direction

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
# met1 bridges: mcons on the contacts' li in the band; track 0 along the band, the others over the
# rows, a met1 width and spacing apart, kept met1 spacing from the rails
MCON_Y = sum(PAD_LI) / 2
TRACK_PITCH = MCON + 2 * M1_CUT + M1_SPACE
# the first track off the band clears the stubs' feet, which reach met1.5 past their mcons
TRACK_FIRST = MCON / 2 + M1_CUT_DIR + M1_SPACE + MCON / 2 + M1_CUT
TRACK_Y = (MCON_Y,) + tuple(  # the band first, then up over the PMOS row, then down over the NMOS row
    y for y in [MCON_Y + TRACK_FIRST + k * TRACK_PITCH for k in range(7)]
    + [MCON_Y - TRACK_FIRST - k * TRACK_PITCH for k in range(7)]
    if y + MCON / 2 + M1_CUT <= FRAME["rails"]["VPWR"]["met1"]["y"][0] - M1_SPACE
    and y - MCON / 2 - M1_CUT >= FRAME["rails"]["VGND"]["met1"]["y"][1] + M1_SPACE)

PAD_HALF = CUT / 2 + LI_CUT_DIR          # half width of an input pad on li
STRIP_HALF = LI / 2                      # half width of a narrow li strip
WIDE_HALF = CUT / 2 + LI_CUT_DIR         # li strip over contacts that does not reach a rail
LANE_Y = {"n": (N_LI[1] - LI, N_LI[1]), "p": (P_LI[0], P_LI[0] + LI)}   # li lane on the row's inner edge
OUTER_Y = {"n": (N_LI[0], N_LI[0] + LI), "p": (P_LI[1] - LI, P_LI[1])}  # li lane on the row's outer edge, by the rail
ROWS = {"n": ("VGND", N_DIFF, N_LI), "p": ("VPWR", P_DIFF, P_LI)}
WIDEN_STEPS = tuple(round(0.06 * k, 2) for k in range(8))   # extra width (um) tried for a column between two gates
MAX_WIDENINGS, MAX_CROSSINGS = 300, 60
MAX_GROWTH = 12    # targeted widening rounds after the search above
BAND_BUDGET, BAND_TRIES = 2000, 20     # search steps, and complete band placements tried, per widening
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
    pad_x: dict = field(default_factory=dict)      # net -> x of its first poly contact
    pads: dict = field(default_factory=dict)       # net -> [(x, first gate, last gate)], one per run of its gates
    joins: dict = field(default_factory=dict)      # net -> ([(x0, x1)] li in the band, [x] mcons of a met1 bridge, its track)
    crossing: dict = field(default_factory=dict)
    diff_x: tuple = (0, 0)
    diff_w: dict = field(default_factory=dict)    # row -> diffusion width under each gate
    cont: dict = field(default_factory=dict)      # row -> contacted columns
    half: dict = field(default_factory=dict)      # (row, column) -> half width of its li strip
    ys: dict = field(default_factory=dict)        # (row, column) -> contact centres
    lanes: dict = field(default_factory=dict)     # row -> [(net, x0, x1, "inner" | "outer")] li along an edge
    jogs: dict = field(default_factory=dict)      # row -> [(net, x)] li across the row where a lane switches edge

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
    diff_w = {"n": [None if g == BREAK else widths.get(("n", g), wn) for g in order.gates],
              "p": [None if g == BREAK else widths.get(("p", g), wp) for g in order.gates]}
    for row, ws in diff_w.items():
        band, widest = ROWS[row][1], max(w for w in ws if w is not None)
        if widest > band[1] - band[0] + 1e-9:
            raise ValueError(f"a {row}MOS {widest} um wide does not fit the row (folding is not built yet)")

    n_cont, p_cont = contacted(order)
    either = n_cont | p_cont
    cols = len(order.gates) + 1

    # Try the cheapest crossings first; if no crossing leaves room for every input's poly contact,
    # widen the columns between gates a step at a time, as HD's nand3_1 and o21ai_1 do.
    inner = list(range(1, cols - 1))
    error = ValueError("no crossing leaves room for the poly contacts")

    def attempt(extra):
        """The plan for these widenings, or None and the gates whose contact found no room."""
        nonlocal error
        col_x, gate_x = columns(order, either, extra)
        options = route_crossings(stage, order, col_x, gate_x, n_cont, p_cont)
        crowded = set()
        for choice in islice(product(*options.values()), MAX_CROSSINGS):
            crossing = dict(zip(options, choice))
            xs = sorted(crossing.values())
            if any(b - a < 2 * STRIP_HALF + LI_SPACE - 1e-9 for a, b in zip(xs, xs[1:])):
                error = ValueError("two crossings meet")
                continue
            try:
                pads, joins = place_pads(order, gate_x, crossing)
                return finish(order, col_x, gate_x, crossing, pads, joins, diff_w, n_cont, p_cont), crowded
            except NoRoom as e:
                crowded.add(e.gate)
                error = e
            except ValueError as e:
                error = e
        return None, crowded

    def search(extra):
        """As attempt, but the crossings and contacts are placed together by midband.solutions, which
        backtracks where place_pads would not: li first, then with met1 bridges where li is full."""
        nonlocal error
        col_x, gate_x = columns(order, either, extra)
        options = route_crossings(stage, order, col_x, gate_x, n_cont, p_cont)
        items = [midband.Item(net, "crossing", STRIP_HALF, candidates=tuple(xs)) for net, xs in options.items()]
        for gate, runs in gate_runs(order).items():
            blocked = tuple((x, CUT / 2 + POLY_CUT + POLY_SPACE + L / 2)
                            for j, x in enumerate(gate_x) if order.gates[j] not in (gate, BREAK))
            items += [midband.Item(gate, "pad", PAD_HALF, gates=(gate_x[first], gate_x[last]), reach=PAD_REACH,
                                blocked=blocked, run=(first, last)) for first, last in runs]
        crowded = set()
        for li_only in (True, False):
            stats = midband.Stats()
            for found in islice(midband.solutions(items, band_clear, GRID, LI_SPACE, li_only, BAND_BUDGET, stats),
                                BAND_TRIES):
                crossing = {items[i].net: x for i, x in found.items() if items[i].kind == "crossing"}
                pads = {}
                for i in sorted(found, key=lambda i: (items[i].kind, items[i].run)):
                    if items[i].kind == "pad":
                        pads.setdefault(items[i].net, []).append((found[i], *items[i].run))
                pads = {gate: pads[gate] for gate in gate_runs(order)}
                try:
                    joins = join_nets(pads, crossing)
                    return finish(order, col_x, gate_x, crossing, pads, joins, diff_w, n_cont, p_cont), crowded
                except ValueError as e:
                    error = e
            crowded |= {items[i].net for i, n in stats.dead.items() if items[i].kind == "pad" and n}
        if crowded:
            error = NoRoom(sorted(crowded)[0])
        return None, crowded

    for extra in islice(widenings(len(inner)), MAX_WIDENINGS):
        plan, _ = attempt(dict(zip(inner, extra)))
        if plan:
            return plan
    # With many columns the cheapest-first search runs out before it reaches the one column that
    # needs widening. Then widen only the columns beside gates whose contact found no room, a step
    # at a time, placing the band by search.
    extra = dict.fromkeys(inner, 0)
    for _ in range(MAX_GROWTH):
        plan, crowded = search(extra)
        if plan:
            return plan
        grow = [i for i in inner if {order.gates[i - 1], order.gates[i]} & crowded]
        if not grow:
            break
        for i in grow:
            extra[i] = round(extra[i] + WIDEN_STEPS[1], 2)
    raise error


class NoRoom(ValueError):
    """No place for a net's poly contact."""
    def __init__(self, gate):
        super().__init__(f"no room for the {gate} contact")
        self.gate = gate


def band_clear(a: midband.Item, b: midband.Item) -> float:
    """Least distance between the centres of two band objects of different nets: li spacing
    between their li, as place_pads and place keep it."""
    half = {"pad": PAD_HALF, "crossing": STRIP_HALF}
    return half[a.kind] + LI_SPACE + half[b.kind]


def gate_runs(order: Order) -> dict:
    """{net: [[first, last]]}: the runs of side-by-side gates of each gate net, left to right."""
    out = {}
    for gate in dict.fromkeys(g for g in order.gates if g != BREAK):
        at = [i for i, g in enumerate(order.gates) if g == gate]
        runs = [[at[0], at[0]]]
        for i in at[1:]:
            if i == runs[-1][1] + 1:
                runs[-1][1] = i
            else:
                runs.append([i, i])
        out[gate] = runs
    return out


def widenings(k: int):
    """Extra widths for k columns, least extra first, then the smallest largest step: WIDEN_STEPS
    indexes, built a total at a time rather than sorted, since 8^k gets large past 5 gates."""
    def split(total, k):
        if k == 0:
            if total == 0:
                yield ()
            return
        for first in range(min(total, len(WIDEN_STEPS) - 1) + 1):
            for rest in split(total - first, k - 1):
                yield (first,) + rest
    for total in range((len(WIDEN_STEPS) - 1) * k + 1):
        for steps in sorted(split(total, k), key=lambda e: (max(e, default=0), e)):
            yield tuple(WIDEN_STEPS[s] for s in steps)


def columns(order: Order, either: set, extra: dict):
    """x of every column and gate, with the left diffusion edge at 0. extra[i] widens column i.
    At a break the diffusion ends past the contact and starts again past diff/tap.3; its "gate"
    x is the middle of the gap."""
    col_x, gate_x = [CUT_DIFF + CUT / 2], []
    for i in range(1, len(order.gates) + 1):
        if order.gates[i - 1] == BREAK:
            edge = col_x[-1] + CUT / 2 + CUT_DIFF + extra.get(i - 1, 0) / 2
            gate_x.append(edge + DIFF_SPACE / 2)
            col_x.append(edge + DIFF_SPACE + CUT_DIFF + CUT / 2 + extra.get(i, 0) / 2)
            continue
        if i - 1 in either:
            left = col_x[-1] + CUT / 2 + CUT_GATE + extra.get(i - 1, 0) / 2
        else:
            left = gate_x[-1] + L / 2 + POLY_SPACE + extra.get(i - 1, 0)
        gate_x.append(left + L / 2)
        right = left + L
        col_x.append(right + CUT_GATE + CUT / 2 + extra.get(i, 0) / 2 if i in either else right + POLY_SPACE / 2)
    return col_x, gate_x


def finish(order, col_x, gate_x, crossing, pads, joins, diff_w, n_cont, p_cont) -> Plan:
    """Cell width, centring, and the li of each row."""
    diff_right = col_x[-1] + CUT / 2 + CUT_DIFF
    gates = [g for g, name in zip(gate_x, order.gates) if name != BREAK]
    pad_xs = [p for runs in pads.values() for p, *_ in runs]
    poly = [g - L / 2 for g in gates] + [p - CUT / 2 - POLY_CUT for p in pad_xs]
    poly_r = [g + L / 2 for g in gates] + [p + CUT / 2 + POLY_CUT for p in pad_xs]
    li = [x - WIDE_HALF for x in col_x] + [p - PAD_HALF for p in pad_xs]
    li_r = [x + WIDE_HALF for x in col_x] + [p + PAD_HALF for p in pad_xs]
    m1 = [min(m) - MCON / 2 - M1_CUT_DIR for _, m, _ in joins.values() if m]
    m1_r = [max(m) + MCON / 2 + M1_CUT_DIR for _, m, _ in joins.values() if m]
    shift = max(DIFF_SPACE / 2, POLY_SPACE / 2 - min(poly), LI_SPACE / 2 - min(li), *(M1_SPACE / 2 - x for x in m1))
    need = max(diff_right + DIFF_SPACE / 2, max(poly_r) + POLY_SPACE / 2, max(li_r) + LI_SPACE / 2,
               *(x + M1_SPACE / 2 for x in m1_r)) + shift
    width = snap(math.ceil(need / SITE - 1e-9) * SITE)
    shift = snap(shift + (width - need) / 2)

    plan = Plan(width=width, diff_x=(shift, snap(shift + diff_right)), diff_w=diff_w,
                cont={"n": n_cont, "p": p_cont}, lanes={"n": [], "p": []}, jogs={"n": [], "p": []})
    plan.col_x = [snap(x + shift) for x in col_x]
    plan.gate_x = [snap(g + shift) for g in gate_x]
    plan.pads = {k: [(snap(p + shift), first, last) for p, first, last in v] for k, v in pads.items()}
    plan.pad_x = {k: v[0][0] for k, v in plan.pads.items()}
    plan.joins = {k: ([(snap(a + shift), snap(b + shift)) for a, b in li_joins], [snap(x + shift) for x in mcons], track)
                  for k, (li_joins, mcons, track) in joins.items()}
    plan.crossing = {k: snap(v + shift) for k, v in crossing.items()}
    for row, nodes in (("n", order.n_nodes), ("p", order.p_nodes)):
        plan_row(plan, row, nodes)
        check_row(plan, row, nodes)
    check_lanes(plan)
    return plan


def check_row(plan: Plan, row: str, nodes):
    """The li of different nets that are not laned, each from its contacts to its crossing, must
    keep li spacing; with one crossing net this always holds, with several it may not."""
    rail, laned = ROWS[row][0], {net for net, *_ in plan.lanes[row]}
    spans = []
    for net in sorted(set(nodes) - {rail} - laned):
        xs = [plan.col_x[j] for j in plan.cont[row] if nodes[j] == net]
        xs += [plan.crossing[net]] if net in plan.crossing else []
        if xs:
            spans.append((net, min(xs) - plan.half_at(row, min(xs)), max(xs) + plan.half_at(row, max(xs))))
    for (a, a0, a1), (b, b0, b1) in combinations(spans, 2):
        if a0 < b1 + LI_SPACE - 1e-9 and b0 < a1 + LI_SPACE - 1e-9:
            raise ValueError(f"{a} and {b} meet in the {row} row")
    for net, x in plan.jogs[row]:
        for other, s0, s1 in spans:
            if other != net and s0 < x + STRIP_HALF + LI_SPACE - 1e-9 and x - STRIP_HALF < s1 + LI_SPACE - 1e-9:
                raise ValueError(f"{other} meets the jog of {net} in the {row} row")


def jog_at(plan: Plan, row: str, left: int, right: int, net: str) -> float:
    """x of a jog of net between contacted columns left and right: li spacing from both strips and
    from the other nets' crossings, in the middle of the room if it can."""
    lo = plan.col_x[left] + plan.half[(row, left)] + LI_SPACE + STRIP_HALF
    hi = plan.col_x[right] - plan.half[(row, right)] - LI_SPACE - STRIP_HALF
    for x in (snap((lo + hi) / 2), math.ceil(lo / GRID - 1e-9) * GRID, math.floor(hi / GRID + 1e-9) * GRID):
        x = round(x, 4)
        if lo - 1e-9 <= x <= hi + 1e-9 and all(abs(x - cx) >= 2 * STRIP_HALF + LI_SPACE - 1e-9
                                               for other, cx in plan.crossing.items() if other != net):
            return x
    raise ValueError(f"no room for {net} to switch edges in the {row} row")


def plan_row(plan: Plan, row: str, nodes):
    """li strip widths, lanes and contacts of one row.

    A strip next to a contact of another signal net is narrow, as in HD, and its contacts keep the
    li.5 overlap at both ends. A net whose contacts lie on both sides of a rail contact joins them
    with a lane along the row's inner edge, and the rail column's contacts move away from the lane
    (HD's nand3_1, a21oi_1 and o21ai_1 do the same). Where it must pass another signal net's
    contact instead, the lane runs along the outer edge, by the rail, and that contact moves inward:
    a rail strip reaches the outer edge and a signal strip the inner one, so each edge can pass
    only one kind. Each stretch between two of the net's contacts picks its own edge, and switches
    edge by a jog wherever it must pass a rail and then a signal (or the other way round)."""
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
            # the contacts in the way, left to right, in runs that take the same edge; between two
            # runs the lane switches edge by a jog, a strip across the row where nothing is contacted
            runs = []
            for k in sorted(near(left(a), right(b), net), key=lambda k: plan.col_x[k]):
                edge = "inner" if nodes[k] == rail else "outer"
                if runs and runs[-1][0] == edge:
                    runs[-1][1].append(k)
                else:
                    runs.append([edge, [k]])
            runs = runs or [["inner", []]]
            x0 = left(a)
            for i, (edge, ks) in enumerate(runs):
                if i + 1 < len(runs):
                    x = jog_at(plan, row, ks[-1], runs[i + 1][1][0], net)
                    plan.jogs[row].append((net, x))
                    x1 = snap(x + STRIP_HALF)
                else:
                    x1 = right(b)
                if stretches and stretches[-1][0] == edge:
                    stretches[-1][2] = x1
                    stretches[-1][3] |= set(ks)
                else:
                    stretches.append([edge, x0, x1, set(ks)])
                if i + 1 < len(runs):
                    x0 = snap(x - STRIP_HALF)
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
        others += [(jx, STRIP_HALF) for net, jx in plan.jogs[row] if net != nodes[j]]
        if all(abs(x - ox) >= WIDE_HALF + oh + LI_SPACE - 1e-9 for ox, oh in others):
            plan.half[(row, j)] = WIDE_HALF

    lane = LANE_Y[row]
    for j in cont:
        ws = [plan.diff_w[row][g] for g in (j - 1, j) if 0 <= g < len(plan.gate_x) and plan.diff_w[row][g] is not None]
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
        # a jog crosses the whole row: no other net's lane may pass it
        for net, x in plan.jogs[row]:
            for other, x0, x1, _ in lanes:
                if other != net and x0 < x + STRIP_HALF + LI_SPACE - 1e-9 and x - STRIP_HALF < x1 + LI_SPACE - 1e-9:
                    raise ValueError(f"the lane of {other} meets the jog of {net} in the {row} row")


def route_crossings(stage, order, col_x, gate_x, n_cont, p_cont) -> dict:
    """For each net in both rows, the x where its li may cross the npc band, best first: on a column
    or over a gate, as HD's nand3_1 does. The net's li in each row reaches from its contacts to the
    crossing; another net's contact in between needs a lane (plan_row): inner past a rail, outer past
    a signal. Options that pass a signal come last. Positions count in half columns: 2k is column k,
    2k + 1 the gate after it."""
    out = {}
    for net in sorted(set(order.n_nodes) & set(order.p_nodes) - {"VGND", "VPWR"}):
        n_cols = [2 * i for i, v in enumerate(order.n_nodes) if v == net and i in n_cont]
        p_cols = [2 * i for i, v in enumerate(order.p_nodes) if v == net and i in p_cont]
        options = []
        for h in range(2 * len(col_x) - 1):
            spans = [(min(n_cols + [h]), max(n_cols + [h]), order.n_nodes, n_cont, "VGND"),
                     (min(p_cols + [h]), max(p_cols + [h]), order.p_nodes, p_cont, "VPWR")]
            jumps, passes, ok = 0, 0, True
            for lo, hi, nodes, cont, rail in spans:
                signals = 0
                for k in range((lo + 1) // 2, hi // 2 + 1):
                    if nodes[k] == net or k not in cont:
                        continue
                    if 2 * k == h:
                        ok = False
                    elif nodes[k] == rail:
                        jumps += 1
                    else:
                        signals += 1
                # past another signal's contact only on an outer lane (plan_row), which must end at a
                # full strip of the net, so the crossing sits on one of the net's own contacts
                if signals and not (h % 2 == 0 and nodes[h // 2] == net and h // 2 in cont):
                    ok = False
                passes += signals
            if not ok:
                continue
            cost = (passes, jumps, sum(hi - lo for lo, hi, *_ in spans), h % 2)
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


def place_pads(order, gate_x, crossing: dict):
    """Poly contacts, {net: [(x, first gate, last gate)]}: one per run of side-by-side gates of a net,
    joined to them by a poly bar. Left to right, each sits at the point nearest its gates (left first
    on a tie), at most PAD_REACH away, that keeps li spacing to the other nets' crossings and the nets
    already placed, and poly spacing to the other gates.

    The middle band is one li track. A net's pads, and its crossing if it is made inside the cell
    (a stage output), are joined along it, so each net takes a stretch of the band that no other
    net may enter: with one pad and no crossing per net, as in a single stage, that is just spacing."""
    pads, taken = {}, []        # taken: (net, li left edge, li right edge) in the band
    for gate, runs in gate_runs(order).items():
        pads[gate] = []
        for first, last in runs:
            lo, hi = gate_x[first], gate_x[last]
            keep_out = [(c, c, PAD_HALF + LI_SPACE + STRIP_HALF) for net, c in crossing.items() if net != gate]
            keep_out += [(a, b, PAD_HALF + LI_SPACE) for net, a, b in taken if net != gate]
            keep_out += [(x, x, CUT / 2 + POLY_CUT + POLY_SPACE + L / 2)
                         for j, x in enumerate(gate_x) if order.gates[j] not in (gate, BREAK)]
            candidates = {gate_x[i] for i in range(first, last + 1)} | {a - d for a, b, d in keep_out} \
                | {b + d for a, b, d in keep_out}
            if gate in crossing:
                candidates.add(crossing[gate])
            reach = lambda p: max(lo - p, 0, p - hi)
            fits = [p for p in map(snap, candidates) if reach(p) <= PAD_REACH + 1e-9
                    and all(p <= a - d + 1e-9 or p >= b + d - 1e-9 for a, b, d in keep_out)]
            if not fits:
                raise NoRoom(gate)
            p = min(fits, key=lambda p: (reach(p), p))
            pads[gate].append((p, first, last))
            taken.append((gate, p - PAD_HALF, p + PAD_HALF))
    return pads, join_nets(pads, crossing)


def join_nets(pads: dict, crossing: dict) -> dict:
    """How each net's pads and own crossing are joined in the middle band: {net: (li joins, mcons)},
    li joins as (x, x) spans between contact centres, mcons as x.

    On li when every net's stretch of the band keeps li spacing from the others, as in a single
    stage. Otherwise the fewest nets move to a met1 bridge (handout step 5: met1 only where li1
    cannot): on li such a net keeps only its contacts, joined where they are too close to part, with
    an mcon on each group, and the bridge takes a track of TRACK_Y (see tracks_for)."""
    groups = {}     # net -> [[first centre, last centre, left edge, right edge]], left to right
    for net in sorted(set(pads) | set(crossing)):
        items = [(p, PAD_HALF) for p, *_ in pads.get(net, [])]
        items += [(crossing[net], STRIP_HALF)] if net in crossing else []
        groups[net] = []
        for x, half in sorted(items):
            g = groups[net]
            if g and x - half < g[-1][3] + LI_SPACE - 1e-9:
                g[-1][1], g[-1][3] = x, max(g[-1][3], x + half)
            else:
                g.append([x, x, x - half, x + half])

    def meet(spans, space):
        for (a, a0, a1), (b, b0, b1) in combinations(spans, 2):
            if a != b and a0 < b1 + space - 1e-9 and b0 < a1 + space - 1e-9:
                return a, b

    def tracks_for(bridged):
        """A met1 track of TRACK_Y for each bridged net, or None. Track 0 runs along the band; the
        others run over a row and reach the band by stubs at the net's mcons. Two nets on one track
        keep apart; a net farther out on the same side keeps its stubs clear of the nearer net's
        span (the band counts as nearer to both sides); nets on opposite sides only keep their
        mcons apart, so interleaved spans can still be bridged."""
        span = {net: (groups[net][0][0] - MCON / 2 - M1_CUT_DIR, groups[net][-1][0] + MCON / 2 + M1_CUT_DIR)
                for net in bridged}
        stub = MCON / 2 + M1_CUT + M1_SPACE
        out = lambda t: TRACK_Y[t] - MCON_Y         # signed distance from the band
        for tracks in product(range(len(TRACK_Y)), repeat=len(bridged)):
            on = dict(zip(bridged, tracks))
            fits = True
            for a, b in combinations(bridged, 2):
                (a0, a1), (b0, b1) = span[a], span[b]
                da, db = out(on[a]), out(on[b])
                if on[a] == on[b]:
                    fits = not (a0 < b1 + M1_SPACE - 1e-9 and b0 < a1 + M1_SPACE - 1e-9)
                elif da * db >= 0:      # the band and one side, or the same side
                    far, near = (a, b) if abs(da) > abs(db) else (b, a)
                    n0, n1 = span[near]
                    fits = all(x + stub <= n0 + 1e-9 or x - stub >= n1 - 1e-9 for x, *_ in groups[far])
                else:
                    fits = all(abs(x - y) >= 2 * (MCON / 2 + M1_CUT) + M1_SPACE - 1e-9
                               for x, *_ in groups[a] for y, *_ in groups[b])
                if not fits:
                    break
            if fits:
                return on
        return None

    first = None
    multi = [net for net, g in groups.items() if len(g) > 1]
    for k in range(len(multi) + 1):
        for bridged in combinations(multi, k):
            li = [(net, g[0][2], g[-1][3]) for net, g in groups.items() if net not in bridged]
            li += [(net, a, b) for net in bridged for _, _, a, b in groups[net]]
            clash = meet(li, LI_SPACE)
            first = first or clash
            on = None if clash else tracks_for(bridged)
            if on is None:
                continue
            return {net: ([(g[0][0], g[-1][1])], [], 0) if net not in bridged else
                    ([(x0, x1) for x0, x1, *_ in g], [x0 for x0, *_ in g], on[net]) for net, g in groups.items()}
    raise ValueError(f"{first[0]} and {first[1]} meet in the middle band, on li and on met1")


def rect(c, layer, x0, y0, x1, y1):
    x0, y0, x1, y1 = map(snap, (x0, y0, x1, y1))
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"empty rectangle on {layer}: {(x0, y0, x1, y1)}")
    c.add_polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layer=LAYER[layer])


def box(c, layer, x, y, w, h):
    rect(c, layer, x - w / 2, y - h / 2, x + w / 2, y + h / 2)


def diffusion(c, plan: Plan, row: str):
    """One diffusion strip per row and piece between breaks. Where the width under two gates
    differs, the edge away from the rail steps at the column between them, as in HD's o21ai_1."""
    ws, col_x = plan.diff_w[row], plan.col_x
    pieces, runs = [], []
    for i, w in enumerate(ws):
        if w is None:
            pieces.append(runs)
            runs = []
            continue
        xa = col_x[i] - CUT / 2 - CUT_DIFF if not runs else col_x[i]
        xb = col_x[i + 1] + CUT / 2 + CUT_DIFF if i + 1 == len(ws) or ws[i + 1] is None else col_x[i + 1]
        if runs and abs(runs[-1][2] - w) < 1e-9:
            runs[-1][1] = xb
        else:
            runs.append([xa, xb, w])
    pieces.append(runs)
    edge, sign = (N_DIFF[0], 1) if row == "n" else (P_DIFF[1], -1)
    for runs in pieces:
        x0, x1 = runs[0][0], runs[-1][1]
        if len(runs) == 1:
            rect(c, "diff", x0, min(edge, edge + sign * runs[0][2]), x1, max(edge, edge + sign * runs[0][2]))
            continue
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
    for g, gate in zip(plan.gate_x, order.gates):
        if gate != BREAK:
            rect(c, "poly", g - L / 2, POLY_Y[0], g + L / 2, POLY_Y[1])

    # poly contacts: one per run of a net's gates, with a poly bar over the run; a net's contacts and
    # its own crossing joined along the middle band, on li or over it on met1; pins on the cell's inputs only
    pins = {}
    for gate, runs in plan.pads.items():
        for p, first, last in runs:
            lo, hi = plan.gate_x[first], plan.gate_x[last]
            box(c, "licon", p, sum(PAD_CUT) / 2, CUT, CUT)
            rect(c, "poly", min(p - CUT / 2 - POLY_CUT, lo - L / 2), PAD_POLY[0],
                 max(p + CUT / 2 + POLY_CUT, hi + L / 2), PAD_POLY[1])
            rect(c, "li", p - PAD_HALF, PAD_LI[0], p + PAD_HALF, PAD_LI[1])
        if gate in stage.inputs:
            p = runs[0][0]
            pins[gate] = (p - PAD_HALF + 0.04, PAD_LI[1] - 0.04 - CUT)
    for net, (li_joins, mcons, track) in plan.joins.items():
        for x0, x1 in li_joins:
            if x1 - x0 > 1e-9:
                rect(c, "li", x0, PAD_LI[0], x1, PAD_LI[1])
        for x in mcons:
            box(c, "mcon", x, MCON_Y, MCON, MCON)
        if mcons and track == 0:    # along the band, met1.5 sideways
            rect(c, "met1", min(mcons) - MCON / 2 - M1_CUT_DIR, MCON_Y - MCON / 2 - M1_CUT,
                 max(mcons) + MCON / 2 + M1_CUT_DIR, MCON_Y + MCON / 2 + M1_CUT)
        elif mcons:                 # a stub from each mcon to the track (met1.5 on the band side), and the track
            y = TRACK_Y[track]
            for x in mcons:
                if y > MCON_Y:
                    y0, y1 = MCON_Y - MCON / 2 - M1_CUT_DIR, y + MCON / 2 + M1_CUT
                else:
                    y0, y1 = y - MCON / 2 - M1_CUT, MCON_Y + MCON / 2 + M1_CUT_DIR
                rect(c, "met1", x - MCON / 2 - M1_CUT, y0, x + MCON / 2 + M1_CUT, y1)
            rect(c, "met1", min(mcons) - MCON / 2 - M1_CUT, y - MCON / 2 - M1_CUT, max(mcons) + MCON / 2 + M1_CUT,
                 y + MCON / 2 + M1_CUT)

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
        for net, x in plan.jogs[row]:
            rect(c, "li", x - STRIP_HALF, li[0], x + STRIP_HALF, li[1])

    p_laned = {net for net, *_ in plan.lanes["p"]}
    for net, x in plan.crossing.items():
        rect(c, "li", x - STRIP_HALF, N_LI[1] - 0.01, x + STRIP_HALF, P_LI[0] + 0.01)
        if net != stage.output:     # a net between stages has no pin
            continue
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
