"""Smallest single static CMOS stage for a truth table.

A stage computes Y = !G, with G built from AND (series) and OR (parallel) of the
inputs in the pull-down network; the pull-up network is its dual. That needs Y
negative unate in every input it depends on. Among all series-parallel forms of G
(inputs may repeat), find the one with the fewest transistors whose pull-down and
pull-up each have at most `max_series` transistors in series.

Truth tables use the project convention: bit i is Y for the input combination in
which input k equals bit k of i.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

N = 4
FULL = (1 << (1 << N)) - 1
VARS = [sum(1 << i for i in range(1 << N) if i >> k & 1) for k in range(N)]


@dataclass(frozen=True)
class Form:
    size: int       # inputs in the form; the stage has 2 * size transistors
    down: int       # series depth of the pull-down (AND adds, OR takes the max)
    up: int         # series depth of the pull-up (OR adds, AND takes the max)
    expr: tuple     # ("in", k) | ("and", a, b) | ("or", a, b)


@lru_cache(maxsize=None)
def forms(max_series: int = 3, max_size: int = 12) -> dict:
    """For every monotone 4-input table, its smallest form for each (down, up) depth pair."""
    by_size = {1: {}}
    for k, t in enumerate(VARS):
        by_size[1][(t, 1, 1)] = ("in", k)
    best = {key: (1, expr) for key, expr in by_size[1].items()}
    for n in range(2, max_size + 1):
        new = {}
        for i in range(1, n // 2 + 1):
            for (ta, da, ua), ea in by_size.get(i, {}).items():
                for (tb, db, ub), eb in by_size.get(n - i, {}).items():
                    for op, t, d, u in (("and", ta & tb, da + db, max(ua, ub)),
                                        ("or", ta | tb, max(da, db), ua + ub)):
                        if d > max_series or u > max_series or (t, d, u) in best or (t, d, u) in new:
                            continue
                        new[(t, d, u)] = (op, ea, eb)
        by_size[n] = new
        for key, expr in new.items():
            best[key] = (n, expr)
    table = {}
    for (t, d, u), (n, expr) in best.items():
        current = table.get(t)
        if current is None or (n, max(d, u)) < (current.size, max(current.down, current.up)):
            table[t] = Form(n, d, u, expr)
    return table


def support(table: int) -> list[int]:
    return [k for k in range(N) if any((table >> i & 1) != (table >> (i ^ 1 << k) & 1) for i in range(1 << N))]


def negative_unate(table: int) -> bool:
    """Y never rises when an input rises."""
    return all(not (table >> i & 1 == 0 and table >> (i | 1 << k) & 1)
               for k in range(N) for i in range(1 << N) if not i >> k & 1)


def widen(table: int, n: int) -> int:
    """An n-input table as a 4-input table that ignores the extra inputs."""
    mask = (1 << n) - 1
    return sum(1 << i for i in range(1 << N) if table >> (i & mask) & 1)


def single_stage(table: int, n: int = N, max_series: int = 3) -> Form | None:
    """The smallest one-stage form of Y = table, or None if Y needs more than one stage."""
    t = widen(table, n)
    if not negative_unate(t) or t in (0, FULL):
        return None
    return forms(max_series).get(FULL ^ t)


def expression(form: Form, names: list[str]) -> str:
    """Y = !(G) in the request syntax, for src.cell.network."""
    def text(e, parent=None):
        if e[0] == "in":
            return names[e[1]]
        op = " & " if e[0] == "and" else " | "
        s = text(e[1], e[0]) + op + text(e[2], e[0])
        return s if parent in (None, e[0]) else f"({s})"
    return f"!({text(form.expr)})"
