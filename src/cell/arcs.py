"""Timing arcs of a single-output cell, from its truth table (option 1 handout, section 5).

    python -m src.cell.arcs <inputs, e.g. A,B> <truth table hex>

An arc is one input pin -> the output. A side setting is a value for every other input under which the
pin controls the output (flipping the pin flips Y). Each setting has a direction: "negative" if Y falls
when the pin rises, "positive" if Y rises. The arc's timing sense follows from the directions of all its
settings: all negative -> negative_unate, all positive -> positive_unate, both -> non_unate.

The characterizer measures every setting and keeps the slowest, as the HD TT library does (section 5).
Truth-table convention (AGENTS.md rule 5): bit i is Y when input k equals bit k of i.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Setting:
    side: dict           # other input -> 0 or 1
    direction: str       # "negative" or "positive"


@dataclass(frozen=True)
class TimingArc:
    pin: str
    sense: str
    settings: tuple[Setting, ...]

    def edges(self):
        """(input edge, output edge, settings that produce it) for every edge pair the arc has."""
        out = []
        for edge_in in ("rise", "fall"):
            for direction in ("negative", "positive"):
                chosen = tuple(s for s in self.settings if s.direction == direction)
                if chosen:
                    edge_out = edge_in if direction == "positive" else ("fall" if edge_in == "rise" else "rise")
                    out.append((edge_in, edge_out, chosen))
        return out


def arcs(inputs: list[str], table: int) -> list[TimingArc]:
    n = len(inputs)
    out = []
    for k, pin in enumerate(inputs):
        settings = []
        for state in range(1 << n):
            if state >> k & 1:
                continue                                    # visit each side setting once, with the pin at 0
            low, high = table >> state & 1, table >> (state | 1 << k) & 1
            if low != high:
                side = {p: state >> j & 1 for j, p in enumerate(inputs) if j != k}
                settings.append(Setting(side, "positive" if high else "negative"))
        if not settings:
            continue                                        # Y does not depend on this pin
        kinds = {s.direction for s in settings}
        sense = "non_unate" if len(kinds) == 2 else f"{kinds.pop()}_unate"
        out.append(TimingArc(pin, sense, tuple(settings)))
    return out


if __name__ == "__main__":
    names = sys.argv[1].split(",")
    for a in arcs(names, int(sys.argv[2], 16)):
        print(f"{a.pin} -> Y: {a.sense}")
        for s in a.settings:
            print(f"    {s.direction:8s} with {s.side}")
