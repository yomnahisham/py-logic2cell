"""Draw a single-stage cell inside the HD frame of given/plan_hd.json.

Columns run left to right: diffusion, gate, diffusion, ... as in the Euler
order. Every wire is li1; met1 is only used for the rails.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import re
from itertools import combinations, islice, product
from pathlib import Path

import gdsfactory as gf

from src.cell import band as midband
from src.cell.network import BREAK, Order, Stage, joined, passes

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
DIFF_PAST_GATE = 0.25   # poly.7 diffusion past a gate, also where its width steps down
POLY_DIFF = 0.075   # poly.4 poly spacing to diffusion
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
# A poly contact's li meets li.5 sideways where the band has room (WIDE_PAD_LI, PAD_HALF_WIDE), and
# otherwise above and below, flush sideways (PAD_LI, PAD_HALF), as HD's nand3_1 does between its gates
PAD_LI = (PAD_CUT[0] - LI_CUT_DIR, PAD_CUT[1] + LI_CUT_DIR)    # 0.995 .. 1.325
WIDE_PAD_LI = (PAD_CUT[0], 1.315)                              # li.6 area, as in HD; also the li joining contacts
PAD_POLY = (PAD_CUT[0] - POLY_CUT_DIR, PAD_CUT[1] + POLY_CUT_DIR)
VGND_LI_TOP = FRAME["rails"]["VGND"]["li1"]["y"][1]            # 0.085
VPWR_LI_BOT = FRAME["rails"]["VPWR"]["li1"]["y"][0]            # 2.635
N_LI = (VGND_LI_TOP + LI_SPACE, PAD_CUT[0] - LI_SPACE)         # 0.255 .. 0.905, as in HD's inv_1
N_UNDER_PAD = PAD_LI[0] - LI_SPACE                             # 0.825: NMOS li top under a narrow pad (Plan.top)
P_LI = (PAD_LI[1] + LI_SPACE, VPWR_LI_BOT - LI_SPACE)          # 1.495 .. 2.465
POLY_Y = (N_DIFF[0] - ENDCAP, P_DIFF[1] + ENDCAP)
# met1 bridges: mcons on the contacts' li in the band; track 0 along the band, the others over the
# rows, a met1 width and spacing apart, kept met1 spacing from the rails
MCON_Y = sum(WIDE_PAD_LI) / 2
TRACK_PITCH = MCON + 2 * M1_CUT + M1_SPACE
# the first track off the band clears the stubs' feet, which reach met1.5 past their mcons
TRACK_FIRST = MCON / 2 + M1_CUT_DIR + M1_SPACE + MCON / 2 + M1_CUT
TRACK_Y = (MCON_Y,) + tuple(  # the band first, then up over the PMOS row, then down over the NMOS row
    y for y in [MCON_Y + TRACK_FIRST + k * TRACK_PITCH for k in range(7)]
    + [MCON_Y - TRACK_FIRST - k * TRACK_PITCH for k in range(7)]
    if y + MCON / 2 + M1_CUT <= FRAME["rails"]["VPWR"]["met1"]["y"][0] - M1_SPACE
    and y - MCON / 2 - M1_CUT >= FRAME["rails"]["VGND"]["met1"]["y"][1] + M1_SPACE)

# met1 bridges along a row (finish): a horizontal met1 line over the row, an mcon on each of the net's
# contact strips at the line's height. Each line keeps met1 spacing from the band's met1 and the rails,
# and its mcons stay on the row's li; lines one track pitch apart.
_M1_HALF = MCON / 2 + M1_CUT
BRIDGE_TRIES = 8    # bridge choices tried per plan (finish), fewest nets first
ROW_TRACKS = {
    "p": tuple(y for y in [max(MCON_Y + 2 * _M1_HALF + M1_SPACE, P_LI[0] + MCON / 2) + k * TRACK_PITCH for k in range(4)]
               if y + _M1_HALF <= FRAME["rails"]["VPWR"]["met1"]["y"][0] - M1_SPACE + 1e-9 and y + MCON / 2 <= P_LI[1] + 1e-9),
    "n": tuple(y for y in [min(MCON_Y - 2 * _M1_HALF - M1_SPACE, N_UNDER_PAD - MCON / 2) - k * TRACK_PITCH for k in range(4)]
               if y - _M1_HALF >= FRAME["rails"]["VGND"]["met1"]["y"][1] + M1_SPACE - 1e-9 and y - MCON / 2 >= N_LI[0] - 1e-9),
}

PAD_HALF = CUT / 2                       # half width of a narrow poly contact pad on li
PAD_HALF_WIDE = CUT / 2 + LI_CUT_DIR     # ... and of a wide one
STRIP_HALF = LI / 2                      # half width of a narrow li strip
WIDE_HALF = CUT / 2 + LI_CUT_DIR         # li strip over contacts that does not reach a rail
LANE_Y = {"n": (N_LI[1] - LI, N_LI[1]), "p": (P_LI[0], P_LI[0] + LI)}   # li lane on the row's inner edge
OUTER_Y = {"n": (N_LI[0], N_LI[0] + LI), "p": (P_LI[1] - LI, P_LI[1])}  # li lane on the row's outer edge, by the rail
ROWS = {"n": ("VGND", N_DIFF, N_LI), "p": ("VPWR", P_DIFF, P_LI)}
WIDEN_STEPS = tuple(round(0.06 * k, 2) for k in range(8))   # extra width (um) tried for a column between two gates
MAX_WIDENINGS, MAX_CROSSINGS = 300, 60
LI_CROSSINGS = 2000     # crossing choices per widening when looking for a plan on li alone (place's li_tries):
                        # and2_1's needs Y_b crossing on its own contact, far down its list
MAX_GROWTH = 12    # targeted widening rounds after the search above
PLACE_BUDGET = 400      # layouts drawn per order, over all its widenings: the best orders of o31ai_1 draw
                        # 262 to 290; a hopeless order of a cell that needs met1 (mux2_1) runs to this limit
TRY_BUDGET = 20000      # crossing choices per order, drawn or not: xor2_1's best order needs 12240, most of
                        # them failing at once because a contact finds no room
BAND_BUDGET, BAND_TRIES = 2000, 20     # search steps, and complete band placements tried, per widening
CROSSING_SHIFTS = tuple(sorted({round(s * 0.03 * k, 2) for k in range(8) for s in (1, -1)}, key=lambda d: (abs(d), d)))   # crossing off a gate (um)
PAD_REACH = 0.40    # farthest a poly contact sits from its gate
PAD_STEPS = 200     # contact positions tried per crossing choice before place_pads gives up


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
    gates: tuple = ()                             # the gate order, BREAK at a break
    col_x: list = field(default_factory=list)
    pad_x: dict = field(default_factory=dict)      # net -> x of its first poly contact
    pads: dict = field(default_factory=dict)       # net -> [(x, first gate, last gate)], one per run of its gates
    narrow: set = field(default_factory=set)       # x of the pads kept narrow (PAD_LI)
    joins: dict = field(default_factory=dict)      # net -> ([(x0, x1)] li in the band, [x] mcons of a met1 bridge, its track)
    crossing: dict = field(default_factory=dict)
    diff_x: tuple = (0, 0)
    diff_w: dict = field(default_factory=dict)    # row -> diffusion width under each gate
    cont: dict = field(default_factory=dict)      # row -> contacted columns
    half: dict = field(default_factory=dict)      # (row, column) -> half width of its li strip
    ys: dict = field(default_factory=dict)        # (row, column) -> contact centres
    lanes: dict = field(default_factory=dict)     # row -> [(net, x0, x1, "inner" | "outer")] li along an edge
    jogs: dict = field(default_factory=dict)      # row -> [(net, x)] li across the row where a lane switches edge
    notches: dict = field(default_factory=dict)   # (row, column) -> (net, x0, x1, y): other nets' li keeps out of x0..x1 short of y
    tall: dict = field(default_factory=dict)      # (row, net, x0, x1) -> inner lane reaching to y, to meet a notched strip
    bridges: dict = field(default_factory=lambda: {"n": {}, "p": {}})   # row -> {net: y of its met1 line along the row}

    def apart(self, row):
        """Nets whose li in this row is a strip on each of its columns: laned or bridged on met1."""
        return {net for net, *_ in self.lanes[row]} | set(self.bridges[row])

    def half_at(self, row, x):
        for j in self.cont[row]:
            if abs(self.col_x[j] - x) < 1e-6:
                return self.half[(row, j)]
        return WIDE_HALF

    def band(self, row, x0, x1, net):
        """y extent of net's li between x0 and x1: the row's li band, less any outer lane of
        another net that passes within li spacing, and in the NMOS row under the band's li."""
        lo, hi = ROWS[row][2]
        for other, a, b, edge in self.lanes[row]:
            if edge == "outer" and other != net and a < x1 + LI_SPACE - 1e-9 and b > x0 - LI_SPACE + 1e-9:
                if row == "n":
                    lo = OUTER_Y["n"][1] + LI_SPACE
                else:
                    hi = OUTER_Y["p"][0] - LI_SPACE
        if row == "n":
            hi = min(hi, self.top(x0, x1, net))
        return lo, hi

    def top(self, x0, x1, net):
        """Highest NMOS li of net between x0 and x1. A narrow pad's li reaches li.5 below its contact,
        so under another net's narrow pad the row stops li spacing below it, as in HD's nand3_1."""
        spans = [(p - PAD_HALF, p + PAD_HALF) for gate, runs in self.pads.items() if gate != net
                 for p, *_ in runs if p in self.narrow]
        if any(a < x1 + LI_SPACE - 1e-9 and b > x0 - LI_SPACE + 1e-9 for a, b in spans):
            return N_UNDER_PAD
        return N_LI[1]

    def strip(self, row, nodes, j):
        """x extent of the li drawn over column j: the column's own strip on a laned net, otherwise
        one strip over all the net's contacts in the row and its crossing."""
        net = nodes[j]
        if net in self.apart(row):
            return self.col_x[j] - self.half[(row, j)], self.col_x[j] + self.half[(row, j)]
        xs = [self.col_x[i] for i in self.cont[row] if nodes[i] == net]
        xs += [self.crossing[net]] if net in self.crossing else []
        return min(xs) - self.half_at(row, min(xs)), max(xs) + self.half_at(row, max(xs))

    def lane_y(self, row, net, x0, x1, edge):
        """y extent of a lane: an inner NMOS lane drops below the band's li where it passes under it."""
        if edge == "outer":
            return OUTER_Y[row]
        tall = self.tall.get((row, net, x0, x1))
        if row == "p":
            return (LANE_Y["p"][0], tall) if tall else LANE_Y["p"]
        hi = self.top(x0, x1, net)
        return (tall, hi) if tall else (hi - LI, hi)


def is_internal(net):
    return net[0] in "np" and net[1:].isdigit()


def contacted(order: Order):
    """Per row, the set of columns that need a contact. A column just past a break that the row
    runs through is the same diffusion as the one before it, and has none."""
    out = []
    for nodes, fets in ((order.n_nodes, order.n_fets), (order.p_nodes, order.p_fets)):
        skip = joined(order.gates, nodes, fets)
        kept = [net for i, net in enumerate(nodes) if i not in skip]
        out.append({i for i, net in enumerate(nodes) if i not in skip and not (is_internal(net) and kept.count(net) == 1)})
    return out


def prepare(order: Order, wn: float, wp: float, widths: dict | None):
    """Diffusion width under each gate per row, the columns where it steps, and the contacted columns."""
    widths = widths or {}
    def width(row, i, g):
        """A transistor's own width, else widths per (kind, gate), else the row's default."""
        fets = order.n_fets if row == "n" else order.p_fets
        own = fets[i].w if fets and fets[i] is not None else None
        return own or widths.get((row, g), wn if row == "n" else wp)

    diff_w = {row: [None if g == BREAK else width(row, i, g) for i, g in enumerate(order.gates)] for row in "np"}
    # a row with the same net on both sides of a break runs on through it, as wide as the narrower side
    for row, nodes, fets in (("n", order.n_nodes, order.n_fets), ("p", order.p_nodes, order.p_fets)):
        for i in joined(order.gates, nodes, fets):
            sides = [diff_w[row][k] for k in (i - 2, i) if 0 <= k < len(order.gates) and diff_w[row][k] is not None]
            diff_w[row][i - 1] = min(sides)
    # columns where the diffusion width changes between the gates on either side (diffusion())
    steps = {i for i in range(1, len(order.gates)) for ws in diff_w.values()
             if ws[i - 1] is not None and ws[i] is not None and abs(ws[i - 1] - ws[i]) > 1e-9
             and BREAK not in (order.gates[i - 1], order.gates[i])}
    for row, ws in diff_w.items():
        band, widest = ROWS[row][1], max(w for w in ws if w is not None)
        if widest > band[1] - band[0] + 1e-9:
            raise ValueError(f"a {row}MOS {widest} um wide does not fit the row (folding is not built yet)")

    n_cont, p_cont = contacted(order)
    return diff_w, steps, n_cont, p_cont


def min_width(order: Order, wn: float = 0.65, wp: float = 1.0, widths: dict | None = None) -> float:
    """A lower bound on the width of any plan of this order: its columns at their closest, with diffusion
    spacing to both cell edges, in whole sites. Widening, poly contacts and li only add to it, so an
    order whose bound is wider than a plan already found cannot beat that plan."""
    _, steps, n_cont, p_cont = prepare(order, wn, wp, widths)
    col_x, _ = columns(order, n_cont | p_cont, {}, steps)
    diff_right = col_x[-1] + CUT / 2 + CUT_DIFF
    return snap(math.ceil((diff_right + DIFF_SPACE) / SITE - 1e-9) * SITE)


def place(stage: Stage, order: Order, wn: float = 0.65, wp: float = 1.0, widths: dict | None = None,
          li_tries: int = 0, grow: bool = True, bridges: bool = False) -> Plan:
    """Raises ValueError when this order cannot be drawn; the caller tries the next one. With li_tries,
    a plan that needs met1 is kept only while that many more widenings find none on li alone. With
    bridges, a row that li cannot route may join a net's contacts by a met1 line along it (finish); the
    build allows it only where li has already failed: folded (stack) cells and split networks."""
    diff_w, steps, n_cont, p_cont = prepare(order, wn, wp, widths)
    either = n_cont | p_cont
    cols = len(order.gates) + 1

    # Try the cheapest crossings first; if no crossing leaves room for every input's poly contact,
    # widen the columns between gates a step at a time, as HD's nand3_1 and o21ai_1 do.
    inner = list(range(1, cols - 1))
    error = ValueError("no crossing leaves room for the poly contacts")

    def attempt(extra):
        """The narrowest plan for these widenings (li only before met1), or None, and the gates whose
        contact found no room. The cheapest crossing is not always the narrowest: in nand3_1 it puts
        A's contact past the last gate. Each crossing is tried with room for wide pads first, which keeps
        the li below them, and then with narrow pads, which pack closer; a tie keeps the first."""
        nonlocal error, spent, tries
        col_x, gate_x = columns(order, either, extra, steps)
        options = route_crossings(stage, order, col_x, gate_x, n_cont, p_cont)
        crowded, best = set(), None
        limit = LI_CROSSINGS if li_tries else MAX_CROSSINGS     # the search for li alone looks further down
        for choice, wide in product(islice(ranked(list(options.values())), limit), (True, False)):
            tries += 1
            crossing = dict(zip(options, choice))
            xs = sorted(crossing.values())
            if any(b - a < 2 * STRIP_HALF + LI_SPACE - 1e-9 for a, b in zip(xs, xs[1:])):
                error = ValueError("two crossings meet")
                continue
            try:
                pads, joins = place_pads(order, gate_x, crossing, wide)
                spent += 1      # only what reaches finish counts: a contact with no room fails at once
                plan = finish(order, col_x, gate_x, crossing, pads, joins, diff_w, n_cont, p_cont, bridges)
            except NoRoom as e:
                crowded.add(e.gate)
                error = e
                continue
            except ValueError as e:
                error = e
                continue
            if best is None or uses_met1(plan) < uses_met1(best) or \
                    (uses_met1(plan) == uses_met1(best) and plan.width < best.width - 1e-9):
                best = plan
        return best, crowded

    def search(extra):
        """As attempt, but the crossings and contacts are placed together by midband.solutions, which
        backtracks where place_pads would not: li first, then with met1 bridges where li is full."""
        nonlocal error
        col_x, gate_x = columns(order, either, extra, steps)
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
                    return finish(order, col_x, gate_x, crossing, pads, joins, diff_w, n_cont, p_cont, bridges), crowded
                except ValueError as e:
                    error = e
            crowded |= {items[i].net for i, n in stats.dead.items() if items[i].kind == "pad" and n}
        if crowded:
            error = NoRoom(sorted(crowded)[0])
        return None, crowded

    # li inside the cell before met1 (handout step 5)
    fallback, since = None, 0
    spent, tries = 0, 0
    for n, extra in enumerate(islice(widenings(len(inner)), MAX_WIDENINGS)):
        plan, _ = attempt(dict(zip(inner, extra)))
        if plan and not uses_met1(plan):
            place.spent = spent
            return plan
        if plan and fallback is None:
            fallback, since = plan, n
        if fallback and n - since >= li_tries:
            break
        if not li_tries and (spent >= PLACE_BUDGET or tries >= TRY_BUDGET):    # li_tries has its own limit     # a fixed budget per order; raise it if a cell is found to need more
            error = ValueError(f"gave up after {tries} tries, {spent} of them drawn")
            break
    if fallback:
        place.spent = spent
        return fallback
    # With many columns the cheapest-first search runs out before it reaches the one column that
    # needs widening. Then widen only the columns beside gates whose contact found no room, a step
    # at a time, placing the band by search.
    extra = dict.fromkeys(inner, 0)
    # this targeted widening has limits of its own (MAX_GROWTH rounds, BAND_BUDGET steps each), so it runs
    # even when the budget above ran out: that is when it is needed, as in maj3_1. It costs much more than
    # the rest, so the build runs it only for the few orders that could still win (grow)
    for _ in range(MAX_GROWTH if grow else 0):
        plan, crowded = search(extra)
        if plan:
            return plan
        grow = [i for i in inner if {order.gates[i - 1], order.gates[i]} & crowded]
        if not grow:
            break
        for i in grow:
            extra[i] = round(extra[i] + WIDEN_STEPS[1], 2)
    raise error


def uses_met1(plan: Plan) -> bool:
    return any(mcons for _, mcons, _ in plan.joins.values()) or any(plan.bridges.values())


class NoRoom(ValueError):
    """No place for a net's poly contact."""
    def __init__(self, gate):
        super().__init__(f"no room for the {gate} contact")
        self.gate = gate


def band_clear(a: midband.Item, b: midband.Item) -> float:
    """Least distance between the centres of two band objects of different nets: li spacing
    between their li, as place_pads and place keep it."""
    half = {"pad": PAD_HALF, "crossing": STRIP_HALF}
    if a.kind == b.kind == "pad":   # and poly spacing between their contacts' poly
        return max(2 * PAD_HALF + LI_SPACE, CUT + 2 * POLY_CUT + POLY_SPACE)
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


def ranked(options: list):
    """One choice from each list, best first by the sum of their places in the lists, so that every
    net's second and third choices come early, not only the last net's, as a plain product would."""
    def split(total, lists):
        if not lists:
            if total == 0:
                yield ()
            return
        for i in range(min(total, len(lists[0]) - 1) + 1):
            for rest in split(total - i, lists[1:]):
                yield (lists[0][i],) + rest
    for total in range(sum(len(o) - 1 for o in options) + 1):
        yield from split(total, options)


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


def columns(order: Order, either: set, extra: dict, steps: set = frozenset()):
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
        if i - 1 in steps:      # the wider diffusion goes poly.7 past its gate, and stops poly.4 short of the next
            left = max(left, gate_x[-1] + L / 2 + DIFF_PAST_GATE + POLY_DIFF)
        gate_x.append(left + L / 2)
        right = left + L
        col_x.append(right + CUT_GATE + CUT / 2 + extra.get(i, 0) / 2 if i in either else right + POLY_SPACE / 2)
    return col_x, gate_x


def finish(order, col_x, gate_x, crossing, pads, joins, diff_w, n_cont, p_cont, bridges: bool = False) -> Plan:
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

    plan = Plan(width=width, gates=tuple(order.gates), diff_x=(shift, snap(shift + diff_right)), diff_w=diff_w,
                cont={"n": n_cont, "p": p_cont}, lanes={"n": [], "p": []}, jogs={"n": [], "p": []})
    plan.col_x = [snap(x + shift) for x in col_x]
    plan.gate_x = [snap(g + shift) for g in gate_x]
    plan.pads = {k: [(snap(p + shift), first, last) for p, first, last in v] for k, v in pads.items()}
    plan.pad_x = {k: v[0][0] for k, v in plan.pads.items()}
    plan.joins = {k: ([(snap(a + shift), snap(b + shift)) for a, b in li_joins], [snap(x + shift) for x in mcons], track)
                  for k, (li_joins, mcons, track) in joins.items()}
    plan.crossing = {k: snap(v + shift) for k, v in crossing.items()}
    pad_shapes(plan)
    rows = (("n", order.n_nodes), ("p", order.p_nodes))
    try:
        route_rows(plan, rows)
        return plan
    except ValueError as error:
        first = error
    if not bridges:
        raise first
    # li alone cannot route the rows: the fewest nets join their contacts in a row by a met1 line along it
    # (handout step 5: met1 only where li1 cannot), as HD's folded nor3_4 does. Only where the band uses no
    # met1 track over the rows, so the lines meet nothing but each other.
    if any(mcons and track for _, mcons, track in plan.joins.values()):
        raise first
    # a fixed number of choices: finish runs once per placement try, so an unbounded search here multiplies
    # the cost of every order that cannot be drawn (f011f ran for hours); the nets the li error names first
    named = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", str(first)))
    for choice in islice(bridge_choices(plan, rows, named), BRIDGE_TRIES):
        plan.bridges = choice
        try:
            route_rows(plan, rows)
            if bridges_fit(plan, rows):
                return plan
        except ValueError:
            pass
    raise first


def route_rows(plan: Plan, rows):
    """The li of both rows (plan_row), from scratch, and its checks."""
    for row, _ in rows:
        plan.lanes[row], plan.jogs[row] = [], []
    plan.half, plan.ys, plan.notches, plan.tall = {}, {}, {}, {}
    for row, nodes in rows:
        plan_row(plan, row, nodes)
        check_row(plan, row, nodes)
    check_lanes(plan)


def bridge_choices(plan: Plan, rows, named: set = frozenset(), most: int = 2):
    """{row: {net: y}} to try, fewest bridged nets first. A net may be bridged in a row where it has two or
    more contacts and, if it crosses to the other row, crosses on one of them; nets whose contacts overlap
    along the row take different tracks."""
    can = []
    for row, nodes in rows:
        rail = ROWS[row][0]
        for net in sorted(set(nodes) - {rail}):
            xs = [plan.col_x[j] for j in plan.cont[row] if nodes[j] == net]
            if len(xs) < 2:
                continue
            if net in plan.crossing and all(abs(plan.crossing[net] - x) > 1e-6 for x in xs):
                continue
            can.append((row, net, min(xs), max(xs)))
    can.sort(key=lambda c: c[1] not in named)       # the nets that met in the li first
    for k in range(1, min(most, len(can)) + 1):
        for picked in combinations(can, k):
            for tracks in product(*(range(len(ROW_TRACKS[row])) for row, *_ in picked)):
                taken, ok = [], True
                for (row, net, a, b), t in zip(picked, tracks):
                    if any(r == row and u == t and a < q + 2 * _M1_HALF + M1_SPACE and p < b + 2 * _M1_HALF + M1_SPACE
                           for r, u, p, q in taken):
                        ok = False
                        break
                    taken.append((row, t, a, b))
                if ok:
                    choice = {"n": {}, "p": {}}
                    for (row, net, *_), t in zip(picked, tracks):
                        choice[row][net] = ROW_TRACKS[row][t]
                    yield choice


def bridges_fit(plan: Plan, rows) -> bool:
    """Every mcon of a met1 line sits on its column's li strip, whatever lanes and notches left of it."""
    for row, nodes in rows:
        for net, y in plan.bridges[row].items():
            for j in plan.cont[row]:
                if nodes[j] != net:
                    continue
                y0, y1 = plan.band(row, *plan.strip(row, nodes, j), net)
                if y - MCON / 2 < y0 - 1e-9 or y + MCON / 2 > y1 + 1e-9:
                    return False
    return True


def pad_shapes(plan: Plan):
    """Pads are placed narrow; each one, left to right, becomes wide where the other nets' li in the band
    keeps li spacing and the cell's edge stays half li spacing away, so the rows below keep their li.
    The rest stay narrow, and the NMOS li under them stops lower (Plan.top)."""
    band = [(net, x - STRIP_HALF, x + STRIP_HALF) for net, x in plan.crossing.items()]
    band += [(net, a - PAD_HALF, b + PAD_HALF) for net, (li, _, _) in plan.joins.items() for a, b in li]
    pads = sorted((p, gate) for gate, runs in plan.pads.items() for p, *_ in runs)
    half = {p: PAD_HALF for p, _ in pads}
    for p, gate in pads:
        a, b = p - PAD_HALF_WIDE, p + PAD_HALF_WIDE
        others = band + [(g, q - half[q], q + half[q]) for q, g in pads if q != p]
        if a >= LI_SPACE / 2 - 1e-9 and b <= plan.width - LI_SPACE / 2 + 1e-9 and \
                all(net == gate or y1 <= a - LI_SPACE + 1e-9 or y0 >= b + LI_SPACE - 1e-9 for net, y0, y1 in others):
            half[p] = PAD_HALF_WIDE
    plan.narrow = {p for p, h in half.items() if h == PAD_HALF}


def check_row(plan: Plan, row: str, nodes):
    """The li of different nets that are not laned, each from its contacts to its crossing, must
    keep li spacing; with one crossing net this always holds, with several it may not."""
    rail, laned = ROWS[row][0], plan.apart(row)
    spans = []
    for net in sorted(set(nodes) - {rail} - laned):
        xs = [plan.col_x[j] for j in plan.cont[row] if nodes[j] == net]
        xs += [plan.crossing[net]] if net in plan.crossing else []
        if xs:
            spans.append((net, min(xs) - plan.half_at(row, min(xs)), max(xs) + plan.half_at(row, max(xs))))
    # a laned net's li is a strip on each of its columns (and its lanes, checked in check_lanes)
    strips = spans + [(net, plan.col_x[j] - plan.half[(row, j)], plan.col_x[j] + plan.half[(row, j)])
                      for j in plan.cont[row] for net in [nodes[j]] if net in laned]
    for (a, a0, a1), (b, b0, b1) in combinations(strips, 2):
        if a != b and a0 < b1 + LI_SPACE - 1e-9 and b0 < a1 + LI_SPACE - 1e-9:
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
    edge by a jog wherever it must pass a rail and then a signal (or the other way round).

    A stretch that ends at the net's crossing may also pass under the near side of a signal column
    beyond it, as Y does under p1 in HD's a21oi_1: that column is notched, its li and contacts stop
    li spacing short of the lane, and its own lane starts past the notch and rises to meet it."""
    rail, band, li = ROWS[row]
    cont = plan.cont[row]
    for j in cont:
        crowded = [k for k in (j - 1, j + 1) if k in cont and nodes[k] not in (rail, nodes[j])]
        plan.half[(row, j)] = STRIP_HALF if nodes[j] == rail or crowded else WIDE_HALF

    def near(x0, x1, net):
        """Contacted columns of other nets whose li strip comes within li spacing of x0..x1."""
        return [k for k in cont if nodes[k] != net and plan.col_x[k] - plan.half[(row, k)] < x1 + LI_SPACE - 1e-9
                and plan.col_x[k] + plan.half[(row, k)] > x0 - LI_SPACE + 1e-9]

    moved, notched = set(), {}      # notched: column -> the net whose lane passes under it
    for net in sorted(set(nodes) - {rail} - set(plan.bridges[row])):
        xs = [plan.col_x[j] for j in cont if nodes[j] == net]
        cx = plan.crossing.get(net)
        if cx is not None:
            xs.append(cx)
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
                beyond = nodes[k] != rail and cx is not None and (b == cx < plan.col_x[k] or plan.col_x[k] < cx == a)
                if beyond:
                    notched[k] = net
                edge = "inner" if nodes[k] == rail or beyond else "outer"
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

    def inner_limit(j, half):
        """How far toward the inner edge the li over column j may reach: li spacing from the inner
        lanes of other nets passing over it, and in the NMOS row below the narrow pads above it."""
        x, net = plan.col_x[j], nodes[j]
        ys = [plan.lane_y(row, other, a, b, e) for other, a, b, e in plan.lanes[row]
              if e == "inner" and other != net and a < x + half + LI_SPACE - 1e-9 and b > x - half - LI_SPACE + 1e-9]
        if row == "n":
            return min([plan.top(x - half, x + half, net)] + [y0 - LI_SPACE for y0, _ in ys])
        return max([li[0]] + [y1 + LI_SPACE for _, y1 in ys])

    def room(j, half):
        """Contacts that fit in column j with a strip of this half width."""
        ends = LI_CUT_DIR if half == STRIP_HALF else 0     # a wide strip meets li.5 sideways
        if row == "n":
            return len(contacts_y(row, width_of(j), hi=inner_limit(j, half) - ends))
        return len(contacts_y(row, width_of(j), lo=inner_limit(j, half) + ends))

    def width_of(j):
        ws = [plan.diff_w[row][g] for g in (j - 1, j) if 0 <= g < len(plan.gate_x) and plan.diff_w[row][g] is not None]
        return min(ws)

    # Under another net's outer lane a narrow strip, which covers its contact by li.5 above and
    # below, leaves no room for the contact in the NMOS row. Widen it where the neighbours allow:
    # li.5 holds on two opposite sides, so a wide strip covers the contact sideways instead. The same
    # goes for a strip whose contact moves away from another net's lane or narrow pad, where a wide
    # strip keeps more contacts.
    for j in cont:
        x = plan.col_x[j]
        if plan.half[(row, j)] != STRIP_HALF:
            continue
        if nodes[j] == rail:
            if room(j, WIDE_HALF) <= room(j, STRIP_HALF):
                continue
        elif j in notched:      # wide, its own lane has room to start past the notch and still meet it
            pass
        elif plan.band(row, *plan.strip(row, nodes, j), nodes[j]) == li:
            continue
        # a notched strip keeps clear of its lane by the notch, and a moved one of the lanes over it,
        # whose crossings and jogs stop at the lane
        mine = {nodes[j], notched.get(j)}
        if j in moved:
            mine |= {net for net, a, b, e in plan.lanes[row] if e == "inner" and
                     a < x + WIDE_HALF + LI_SPACE - 1e-9 and b > x - WIDE_HALF - LI_SPACE + 1e-9}
        others = [(plan.col_x[k], plan.half[(row, k)]) for k in cont if nodes[k] != nodes[j]]
        others += [(cx, plan.half_at(row, cx)) for net, cx in plan.crossing.items() if net not in mine]
        others += [(jx, STRIP_HALF) for net, jx in plan.jogs[row] if net not in mine]
        if nodes[j] == rail:    # it reaches the outer edge, and the inner one where no lane passes over it
            others += [((a + b) / 2, (b - a) / 2) for net, a, b, e in plan.lanes[row]
                       if e == "outer" or j not in moved]
        if all(abs(x - ox) >= WIDE_HALF + oh + LI_SPACE - 1e-9 for ox, oh in others):
            plan.half[(row, j)] = WIDE_HALF
            continue
        if nodes[j] != rail:
            continue
        # A rail strip that needs the room may take it from a wide signal neighbour that keeps a contact
        # when narrow, as HD's a21oi_1 does: VGND wide, Y beside it narrow with one contact.
        give = [k for k in cont if nodes[k] not in (rail, nodes[j]) and plan.half[(row, k)] == WIDE_HALF
                and abs(plan.col_x[k] - x) < WIDE_HALF + WIDE_HALF + LI_SPACE - 1e-9]
        rest = [(ox, oh) for ox, oh in others if all(abs(ox - plan.col_x[k]) > 1e-9 for k in give)]
        rest += [(plan.col_x[k], STRIP_HALF) for k in give]
        if give and all(abs(x - ox) >= WIDE_HALF + oh + LI_SPACE - 1e-9 for ox, oh in rest):
            narrowed = []
            for k in give:
                kx = plan.col_x[k]
                top = min(li[1], plan.band(row, kx - STRIP_HALF, kx + STRIP_HALF, nodes[k])[1])
                bottom = max(li[0], plan.band(row, kx - STRIP_HALF, kx + STRIP_HALF, nodes[k])[0])
                if contacts_y(row, width_of(k), bottom + LI_CUT_DIR, top - LI_CUT_DIR):
                    narrowed.append(k)
            if len(narrowed) == len(give):
                for k in give:
                    plan.half[(row, k)] = STRIP_HALF
                plan.half[(row, j)] = WIDE_HALF

    # a notched column's own lane starts li spacing past the lane under it, and rises to its strip
    for k, under in notched.items():
        x, half = plan.col_x[k], plan.half[(row, k)]
        (z0, z1), = [(a - LI_SPACE, b + LI_SPACE) for net, a, b, e in plan.lanes[row] if net == under
                     and e == "inner" and a < x + half + LI_SPACE - 1e-9 and b > x - half - LI_SPACE + 1e-9]
        edge_y = inner_limit(k, half)
        plan.notches[(row, k)] = (under, z0, z1, edge_y)
        for i, (net, a, b, e) in enumerate(plan.lanes[row]):
            if net != nodes[k] or e != "inner" or not (a < z1 - 1e-9 and b > z0 + 1e-9):
                continue
            a, b = (snap(z1), b) if x > (z0 + z1) / 2 else (a, snap(z0))
            if min(b, x + half) - max(a, x - half) < -1e-9 or b - a < LI - 1e-9:
                raise ValueError(f"no room for {net} past the notch in column {k} of the {row} row")
            plan.lanes[row][i] = (net, a, b, e)
            plan.tall[(row, net, a, b)] = edge_y + (LI if row == "p" else -LI)

    for j in cont:
        lo, hi = -math.inf, math.inf
        half = plan.half[(row, j)]
        ends = LI_CUT_DIR if half == STRIP_HALF else 0     # a wide strip meets li.5 sideways
        if nodes[j] != rail and half == STRIP_HALF:      # li.5 above and below
            lo, hi = li[0] + LI_CUT_DIR, li[1] - LI_CUT_DIR
        if j in moved or j in notched or (nodes[j] == rail and row == "n"):
            if row == "n":
                hi = min(hi, inner_limit(j, half) - ends)
            else:
                lo = max(lo, inner_limit(j, half) + ends)
        band = plan.band(row, *plan.strip(row, nodes, j), nodes[j])
        if nodes[j] != rail and band != li:     # under another net's outer lane or the band's li: the strip and its contacts move inward
            lo, hi = max(lo, band[0] + ends), min(hi, band[1] - ends)
        ys = contacts_y(row, width_of(j), lo, hi)
        if not ys:
            raise ValueError(f"no room for a contact in column {j} of the {row} row")
        plan.ys[(row, j)] = ys


def check_lanes(plan: Plan):
    """Lanes on the same edge must keep li spacing from each other, and inner lanes from the other
    nets' crossings."""
    for row, lanes in plan.lanes.items():
        for i, (net, x0, x1, edge) in enumerate(lanes):
            for other, y0, y1, e in lanes[i + 1:]:
                if e == edge and other != net and x0 < y1 + LI_SPACE - 1e-9 and y0 < x1 + LI_SPACE - 1e-9:
                    raise ValueError(f"the lanes of {net} and {other} meet in the {row} row")
            if edge == "outer":
                continue
            for other, x in plan.crossing.items():
                if other != net and x0 - LI_SPACE < x + STRIP_HALF - 1e-9 and x - STRIP_HALF < x1 + LI_SPACE - 1e-9:
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


def place_pads(order, gate_x, crossing: dict, wide: bool = False):
    """Poly contacts, {net: [(x, first gate, last gate)]}: one per run of side-by-side gates of a net,
    joined to them by a poly bar. Left to right, each sits at a point at most PAD_REACH from its gates
    that keeps li spacing to the other nets' crossings and contacts, and poly spacing from the other
    gates and the other contacts' poly bars; nearest its gates first (left first on a tie). Where a
    later contact finds no room, an earlier one moves to its next point, as B1 does in HD's a21o_1 to
    leave room for A1. With wide, each contact tries the points with room for a wide pad first.

    The middle band is one li track. A net's pads, and its crossing if it is made inside the cell
    (a stage output), are joined along it, so each net takes a stretch of the band that no other
    net may enter: with one pad and no crossing per net, as in a single stage, that is just spacing."""
    bar = lambda p, lo, hi: (min(p - CUT / 2 - POLY_CUT, lo - L / 2), max(p + CUT / 2 + POLY_CUT, hi + L / 2))
    items = [(gate, first, last) for gate, runs in gate_runs(order).items() for first, last in runs]

    def points(gate, first, last, taken, bars):
        """(x, half) a contact may take, best first."""
        lo, hi = gate_x[first], gate_x[last]
        reach = lambda p: max(lo - p, 0, p - hi)
        out = []
        for half in (PAD_HALF_WIDE, PAD_HALF) if wide else (PAD_HALF,):
            keep_out = [(c, c, half + LI_SPACE + STRIP_HALF) for net, c in crossing.items() if net != gate]
            keep_out += [(a, b, half + LI_SPACE) for net, a, b in taken if net != gate]
            # another contact of the same net (a second run of its gates) keeps the contact pitch, licon.2
            keep_out += [((a + b) / 2, (a + b) / 2, CUT_PITCH) for net, a, b in taken if net == gate]
            keep_out += [(x, x, CUT / 2 + POLY_CUT + POLY_SPACE + L / 2)
                         for j, x in enumerate(gate_x) if order.gates[j] not in (gate, BREAK)]
            poly = [(a - POLY_SPACE, b + POLY_SPACE) for net, a, b in bars if net != gate]
            candidates = {gate_x[i] for i in range(first, last + 1)} | {a - d for a, b, d in keep_out} \
                | {b + d for a, b, d in keep_out} | {a - CUT / 2 - POLY_CUT for a, b in poly} \
                | {b + CUT / 2 + POLY_CUT for a, b in poly}
            if gate in crossing:
                candidates.add(crossing[gate])
            # a bar of the same net's other run either joins this one or keeps poly spacing, poly.2
            own = [(a, b) for net, a, b in bars if net == gate]
            candidates |= {a - POLY_SPACE - CUT / 2 - POLY_CUT for a, b in own} \
                | {b + POLY_SPACE + CUT / 2 + POLY_CUT for a, b in own}
            fits = [p for p in map(snap, candidates) if reach(p) <= PAD_REACH + 1e-9
                    and all(p <= a - d + 1e-9 or p >= b + d - 1e-9 for a, b, d in keep_out)
                    and all(bar(p, lo, hi)[1] <= a + 1e-9 or bar(p, lo, hi)[0] >= b - 1e-9 for a, b in poly)
                    and all(bar(p, lo, hi)[1] >= a - 1e-9 and bar(p, lo, hi)[0] <= b + 1e-9
                            or bar(p, lo, hi)[1] <= a - POLY_SPACE + 1e-9 or bar(p, lo, hi)[0] >= b + POLY_SPACE - 1e-9
                            for a, b in own)]
            out += [(p, half) for p in sorted(fits, key=lambda p: (reach(p), p)) if (p, half) not in out]
        return out

    steps, deepest = [PAD_STEPS], [0]

    def place_from(i, taken, bars):
        if i == len(items):
            return []
        deepest[0] = max(deepest[0], i)
        gate, first, last = items[i]
        for p, half in points(gate, first, last, taken, bars):
            steps[0] -= 1
            if steps[0] < 0:
                return None
            rest = place_from(i + 1, taken + [(gate, p - half, p + half)],
                              bars + [(gate, *bar(p, gate_x[first], gate_x[last]))])
            if rest is not None:
                return [(gate, p, first, last)] + rest
        return None

    found = place_from(0, [], [])
    if found is None:
        raise NoRoom(items[deepest[0]][0])
    pads = {gate: [] for gate, *_ in items}
    for gate, p, first, last in found:
        pads[gate].append((p, first, last))
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
    differs, the edge away from the rail steps poly.7 past the wider gate, as in HD's o21ai_1."""
    ws, col_x = plan.diff_w[row], plan.col_x

    def step(k):
        """x where the diffusion width changes at column k, between gates k - 1 and k."""
        if abs(ws[k - 1] - ws[k]) < 1e-9 or BREAK in (plan_gates[k - 1], plan_gates[k]):
            return col_x[k]
        if ws[k - 1] > ws[k]:
            return plan.gate_x[k - 1] + L / 2 + DIFF_PAST_GATE
        return plan.gate_x[k] - L / 2 - DIFF_PAST_GATE

    plan_gates = plan.gates
    pieces, runs = [], []
    for i, w in enumerate(ws):
        if w is None:
            pieces.append(runs)
            runs = []
            continue
        xa = col_x[i] - CUT / 2 - CUT_DIFF if not runs else step(i)
        xb = col_x[i + 1] + CUT / 2 + CUT_DIFF if i + 1 == len(ws) or ws[i + 1] is None else step(i + 1)
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


def notched(c, plan: Plan, row, net, x0, y0, x1, y1):
    """net's li over x0..x1, y0..y1, less the notches other nets' lanes cut into it: what is left
    beyond the notch, and beside it where at least an li width remains."""
    pieces = [(x0, y0, x1, y1)]
    for (r, _), (under, z0, z1, zy) in plan.notches.items():
        if r != row or under == net:
            continue
        out = []
        for a, b, d, e in pieces:
            lo, hi = (b, min(e, zy)) if row == "p" else (max(b, zy), e)
            if z0 >= d or z1 <= a or lo >= hi:
                out.append((a, b, d, e))
                continue
            out += [(a, zy, d, e) if row == "p" else (a, b, d, zy),
                    (a, lo, min(d, z0), hi), (max(a, z1), lo, d, hi)]
        pieces = [(a, b, d, e) for a, b, d, e in out if d - a >= LI - 1e-9 and e - b >= LI - 1e-9]
    for piece in pieces:
        rect(c, "li", *piece)


def draw(name: str, stage: Stage, order: Order, wn: float = 0.65, wp: float = 1.0, widths: dict | None = None):
    gf.gpdk.PDK.activate()
    plan = place(stage, order, wn, wp, widths)
    w = plan.width
    old = gf.kcl.layout_cell(name)      # a cell drawn earlier in this run under the same name (--style tuned)
    if old is not None:
        gf.kcl.delete_cell(old.cell_index())
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
    # a gate where one row has no transistor (unequal folding) stops at the poly contact's bar in the
    # middle band instead of crossing that row's diffusion
    no_n, no_p = passes(order, "n"), passes(order, "p")
    for i, (g, gate) in enumerate(zip(plan.gate_x, order.gates)):
        if gate != BREAK:
            rect(c, "poly", g - L / 2, PAD_POLY[0] if i in no_n else POLY_Y[0], g + L / 2,
                 PAD_POLY[1] if i in no_p else POLY_Y[1])

    # poly contacts: one per run of a net's gates, with a poly bar over the run; a net's contacts and
    # its own crossing joined along the middle band, on li or over it on met1; pins on the cell's inputs only
    pins = {}
    for gate, runs in plan.pads.items():
        for p, first, last in runs:
            lo, hi = plan.gate_x[first], plan.gate_x[last]
            box(c, "licon", p, sum(PAD_CUT) / 2, CUT, CUT)
            rect(c, "poly", min(p - CUT / 2 - POLY_CUT, lo - L / 2), PAD_POLY[0],
                 max(p + CUT / 2 + POLY_CUT, hi + L / 2), PAD_POLY[1])
            if p in plan.narrow:
                rect(c, "li", p - PAD_HALF, PAD_LI[0], p + PAD_HALF, PAD_LI[1])
            else:
                rect(c, "li", p - PAD_HALF_WIDE, WIDE_PAD_LI[0], p + PAD_HALF_WIDE, WIDE_PAD_LI[1])
        if gate not in stage.inputs:
            # a net between stages gets its name on its contact's li, no pin: Magic then names the net
            # after it, and stress.py finds the transistors it drives by that name, as for an input
            c.add_label(gate, position=(snap(runs[0][0]), snap(sum(PAD_CUT) / 2)), layer=LAYER["li_label"])
        if gate in stage.inputs:
            p = runs[0][0]
            if p in plan.narrow:    # as wide as its pad, starting on bare li below the contact
                pins[gate] = (p - PAD_HALF, PAD_LI[0] + 0.04, "narrow")
            else:
                pins[gate] = (p - PAD_HALF_WIDE + 0.04, WIDE_PAD_LI[1] - 0.04 - CUT)
    for net, (li_joins, mcons, track) in plan.joins.items():
        for x0, x1 in li_joins:
            if x1 - x0 > 1e-9:
                rect(c, "li", x0, WIDE_PAD_LI[0], x1, WIDE_PAD_LI[1])
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
    tops = {}   # (row, net) -> (x0, x1, top y) of each li strip drawn for net
    for row, nodes, li, rail in rows:
        cont = plan.cont[row]
        for i in sorted(cont):
            x, ys = plan.col_x[i], plan.ys[(row, i)]
            for y in ys:
                box(c, "licon", x, y, CUT, CUT)
            if nodes[i] == rail:
                half = plan.half[(row, i)]
                ends = LI_CUT_DIR if half == STRIP_HALF else 0      # a wide strip meets li.5 sideways
                if rail == "VGND":
                    lo, hi = -VGND_LI_TOP, ys[-1] + CUT / 2 + ends
                else:
                    lo, hi = ys[0] - CUT / 2 - LI_CUT_DIR, HEIGHT + VGND_LI_TOP
                rect(c, "li", x - half, lo, x + half, hi)
        # nets with more than one contact in this row, or that cross to the other row
        laned = plan.apart(row)
        for net, y in plan.bridges[row].items():
            xs = [plan.col_x[i] for i in cont if nodes[i] == net]
            for x in xs:
                box(c, "mcon", x, y, MCON, MCON)
            rect(c, "met1", min(xs) - MCON / 2 - M1_CUT_DIR, y - _M1_HALF, max(xs) + MCON / 2 + M1_CUT_DIR, y + _M1_HALF)
        for net in sorted(set(nodes) - {rail}):
            xs = [plan.col_x[i] for i in cont if nodes[i] == net]
            if net in laned:
                for x in xs:
                    x0, x1 = x - plan.half_at(row, x), x + plan.half_at(row, x)
                    y0, y1 = plan.band(row, x0, x1, net)
                    notched(c, plan, row, net, x0, y0, x1, y1)
                    tops.setdefault((row, net), []).append((x0, x1, y1))
                continue
            if net in plan.crossing:
                xs.append(plan.crossing[net])
            if not xs:
                continue
            x0, x1 = min(xs) - plan.half_at(row, min(xs)), max(xs) + plan.half_at(row, max(xs))
            y0, y1 = plan.band(row, x0, x1, net)
            notched(c, plan, row, net, x0, y0, x1, y1)
            tops.setdefault((row, net), []).append((x0, x1, y1))
        for net, x0, x1, edge in plan.lanes[row]:
            y0, y1 = plan.lane_y(row, net, x0, x1, edge)
            rect(c, "li", x0, y0, x1, y1)
            tops.setdefault((row, net), []).append((x0, x1, y1))
        for net, x in plan.jogs[row]:
            rect(c, "li", x - STRIP_HALF, li[0], x + STRIP_HALF,
                 plan.top(x - STRIP_HALF, x + STRIP_HALF, net) if row == "n" else li[1])

    p_laned = plan.apart("p")
    for net, x in plan.crossing.items():
        # down into the net's NMOS li, which stops lower under the band's li
        below = [y for x0, x1, y in tops.get(("n", net), []) if x0 <= x - STRIP_HALF + 1e-9 and x + STRIP_HALF <= x1 + 1e-9]
        bottom = min(N_LI[1], max(below, default=N_LI[1]))
        rect(c, "li", x - STRIP_HALF, bottom - 0.01, x + STRIP_HALF, P_LI[0] + 0.01)
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
