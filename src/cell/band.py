"""Places the crossings and poly contacts of the middle band together, by backtracking search.

The middle band (the npc band between the rows) is a line. Each net puts objects on it: a crossing,
where its li passes between the rows, and a poly contact (pad) for each run of its gates. Objects of
different nets must keep a minimum distance, and pads must also keep clear of other nets' gates.
layout.place_pads places pads greedily, left to right, and never revisits a choice; this module tries
the other choices when a later object finds no room. It knows no design rules: the distances come in
from layout.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Item:
    net: str
    kind: str                   # "crossing" or "pad"
    half: float                 # half width of its li in the band
    candidates: tuple = ()      # crossing: allowed x, best first
    gates: tuple = ()           # pad: (left, right) x of its run of gates
    reach: float = 0            # pad: farthest from its gates
    blocked: tuple = ()         # pad: (x, distance) of other nets' gates
    run: tuple = ()             # pad: (first, last) index of its gates in the order


@dataclass
class Stats:
    nodes: int = 0
    dead: dict = field(default_factory=dict)    # item index -> times it found no room


def solutions(items: list[Item], clear, grid: float, li_space: float, li_only: bool, budget: int, stats: Stats):
    """Yield {item index: x}, every object placed, best choices first. clear(a, b) is the least
    distance between the centres of objects of two different nets. With li_only, each net's stretch
    of the band (from its leftmost to its rightmost object) also keeps li_space from every other
    net's, so it can be joined on li. Stops after `budget` search steps."""
    order = sorted(range(len(items)), key=lambda i: (items[i].kind != "crossing", window(items[i])[0]))
    placed = {}

    def free(i):
        """x values item i may take now, best first."""
        item = items[i]
        keep = [(placed[j] - clear(item, items[j]), placed[j] + clear(item, items[j]))
                for j in placed if items[j].net != item.net]
        if item.kind == "crossing":
            return [x for x in item.candidates if all(not (a + 1e-9 < x < b - 1e-9) for a, b in keep)]
        keep += [(x - d, x + d) for x, d in item.blocked]
        lo, hi = window(item)
        spans = [(math.ceil(lo / grid - 1e-9) * grid, math.floor(hi / grid + 1e-9) * grid)]
        for a, b in sorted(keep):
            out = []
            for s0, s1 in spans:
                if b <= s0 + 1e-9 or a >= s1 - 1e-9:
                    out.append((s0, s1))
                    continue
                if a > s0 + 1e-9:
                    out.append((s0, math.floor(a / grid + 1e-9) * grid))
                if b < s1 - 1e-9:
                    out.append((math.ceil(b / grid - 1e-9) * grid, s1))
            spans = [(s0, s1) for s0, s1 in out if s1 >= s0 - 1e-9]
        g0, g1 = item.gates
        points = set()
        for s0, s1 in spans:
            points |= {s0, s1}
            if s0 <= g1 + 1e-9 and s1 >= g0 - 1e-9:     # the span meets the run: its leftmost point on it
                points.add(min(max(s0, math.ceil(g0 / grid - 1e-9) * grid), s1))
        distance = lambda x: max(g0 - x, 0, x - g1)
        return sorted((round(x, 4) for x in points), key=lambda x: (distance(x), x))

    def stretches_apart(i):
        """With li_only: the stretch of item i's net, so far, keeps li_space from the others'."""
        if not li_only:
            return True
        hull = {}
        for j, x in placed.items():
            a, b = hull.get(items[j].net, (math.inf, -math.inf))
            hull[items[j].net] = (min(a, x - items[j].half), max(b, x + items[j].half))
        a0, a1 = hull[items[i].net]
        return all(b0 >= a1 + li_space - 1e-9 or b1 <= a0 - li_space + 1e-9
                   for net, (b0, b1) in hull.items() if net != items[i].net)

    def search(k):
        if stats.nodes >= budget:
            return
        if k == len(order):
            yield dict(placed)
            return
        i = order[k]
        for x in free(i):
            stats.nodes += 1
            placed[i] = x
            if stretches_apart(i) and all(free(j) for j in order[k + 1:]):
                yield from search(k + 1)
            else:
                blocked = next((j for j in order[k + 1:] if not free(j)), i)
                stats.dead[blocked] = stats.dead.get(blocked, 0) + 1
            del placed[i]
            if stats.nodes >= budget:
                return

    yield from search(0)


def window(item: Item) -> tuple[float, float]:
    if item.kind == "crossing":
        return min(item.candidates), max(item.candidates)
    return item.gates[0] - item.reach, item.gates[1] + item.reach
