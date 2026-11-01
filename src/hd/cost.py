"""What building a function as static CMOS costs (option 2 handout, section 4, step 4).

The structure is the one Option 1's tool builds (src/cell/network.py, split): inverters on
some inputs, then one complex stage over the inputs and their inverses, then an inverter on
the output if that is smaller. The complex stage computes !G with G a series-parallel form
of at most 4 signals, at most `max_series` transistors in series in either network, taken
from src.common.stage.forms. A function with no such structure is not buildable (None).

Truth tables use the project convention: bit i is Y when input k equals bit k of i.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from src.common.stage import FULL, N, VARS, Form, forms, support, widen


@dataclass(frozen=True)
class Cost:
    signals: tuple[tuple[int, bool], ...]   # inputs of the complex stage: (input k, inverted)
    form: Form                              # G over the signals; the complex stage is !G
    out_inverter: bool

    @property
    def inverted(self) -> tuple[int, ...]:
        return tuple(k for k, inv in self.signals if inv)

    @property
    def inverters(self) -> int:
        return len(self.inverted) + self.out_inverter

    @property
    def stages(self) -> int:
        return self.inverters + 1

    @property
    def transistors(self) -> int:
        return 2 * self.form.size + 2 * self.inverters

    @property
    def series(self) -> int:
        """Most transistors in series in any stage (an inverter has 1)."""
        return max(self.form.down, self.form.up)


def rises(g: int, k: int) -> bool:
    """g goes from 0 to 1 for some input combination when input k goes from 0 to 1."""
    return any(not g >> i & 1 and g >> (i | 1 << k) & 1 for i in range(1 << N) if not i >> k & 1)


def cost(table: int, n: int = N, max_series: int = 3) -> Cost | None:
    """The cheapest build of Y = table (n inputs): fewest transistors, then fewest stages."""
    t = widen(table, n)
    if t in (0, FULL):
        return None
    best = None
    for out_inverter in (False, True):
        # the complex stage computes !G: G = !Y without an output inverter, G = Y with one
        g = t if out_inverter else FULL ^ t
        # G must rise with each of its signals: input k itself where G rises with k,
        # its inverse where G falls with k (both for an input G is binate in)
        signals = []
        for k in support(t):
            signals += [(k, False)] * rises(g, k) + [(k, True)] * rises(FULL ^ g, k)
        if len(signals) > N:
            continue
        # G over the signals: true wherever some on-set point of g is at or below the signal
        # values. On combinations where every inverse is the inverse of its input this is g.
        on = [i for i in range(1 << N) if g >> i & 1]
        over = sum(1 << m for m in range(1 << len(signals))
                   if any(all((i >> k & 1) ^ inv <= (m >> j & 1) for j, (k, inv) in enumerate(signals))
                          for i in on))
        form = forms(max_series).get(widen(over, len(signals)))
        if form is None:
            continue
        candidate = Cost(tuple(signals), form, out_inverter)
        if best is None or (candidate.transistors, candidate.stages) < (best.transistors, best.stages):
            best = candidate
    return best


def evaluate(c: Cost, i: int) -> int:
    """Y of the built network for input combination i, from the form itself, as a check."""
    values = [(i >> k & 1) ^ inv for k, inv in c.signals]

    def g(e):
        if e[0] == "in":
            return values[e[1]]
        a, b = g(e[1]), g(e[2])
        return a & b if e[0] == "and" else a | b

    y = 1 - g(c.form.expr)
    return 1 - y if c.out_inverter else y


def expression(c: Cost, names: list[str]) -> str:
    """Y in the request syntax (!, &, |, parentheses), following the built network."""
    signal = [f"!{names[k]}" if inv else names[k] for k, inv in c.signals]

    def text(e, parent=None):
        if e[0] == "in":
            return signal[e[1]]
        op = " & " if e[0] == "and" else " | "
        s = text(e[1], e[0]) + op + text(e[2], e[0])
        return s if parent in (None, e[0]) else f"({s})"

    g = text(c.form.expr)
    return g if c.out_inverter else f"!({g})"


@dataclass(frozen=True)
class Estimate:
    """The cost of any function: Option 1's structure when it can build it (buildable), otherwise
    a Shannon split Y = x ? F1 : F0 whose halves are estimated the same way and joined by one
    network that cost() can build (a mux, an xor when F1 = !F0, an and/or when a half is constant)."""
    stages: int
    inverters: int
    transistors: int
    series: int
    expression: str     # over the input names A, B, C, D
    buildable: bool


def literal(f: int) -> tuple[int, bool] | None:
    """(k, inverted) when f is input k or its inverse."""
    for k, v in enumerate(VARS):
        if f in (v, FULL ^ v):
            return k, f != v
    return None


@lru_cache(maxsize=None)
def estimate(table: int, n: int = N) -> Estimate | None:
    """The cheapest estimate of Y = table (n inputs): fewest transistors, then fewest stages."""
    t = widen(table, n)
    if t in (0, FULL):
        return None
    c = cost(t)
    if c is not None:
        return Estimate(c.stages, c.inverters, c.transistors, c.series, expression(c, list("ABCD")), True)
    best = None
    for x in support(t):
        halves = [sum(1 << i for i in range(1 << N) if t >> (i & ~(1 << x) | b << x) & 1) for b in (0, 1)]
        if halves[1] == FULL ^ halves[0]:
            halves, xor = halves[:1], True
        else:
            xor = False
        # The joining network's signals: x first, then one per half that is not a constant. A half
        # that is an input or its inverse is that input's wire (the inversion goes into the joining
        # network); any other half is a sub-function with its own estimate.
        names, parts, ref = ["ABCD"[x]], [], []
        for f in halves:
            lit = literal(f)
            if f in (0, FULL):
                ref.append(None)
            elif lit:
                names.append("ABCD"[lit[0]])
                ref.append((len(names) - 1, lit[1]))
            else:
                parts.append(estimate(f))
                names.append(f"({parts[-1].expression})")
                ref.append((len(names) - 1, False))

        def half(j, i):
            """Half j's value when the joining network's signals are the bits of i."""
            if ref[j] is None:
                return halves[j] & 1
            position, inverted = ref[j]
            return (i >> position & 1) ^ inverted

        g = 0
        for i in range(1 << len(names)):
            y = (i & 1) ^ half(0, i) if xor else half(i & 1, i)
            g |= y << i
        joint = cost(g, len(names))
        e = Estimate(stages=joint.stages + sum(p.stages for p in parts),
                     inverters=joint.inverters + sum(p.inverters for p in parts),
                     transistors=joint.transistors + sum(p.transistors for p in parts),
                     series=max([joint.series] + [p.series for p in parts]),
                     expression=expression(joint, names), buildable=False)
        if best is None or (e.transistors, e.stages) < (best.transistors, best.stages):
            best = e
    return best


def gated(c: Cost, k: int) -> int:
    """Transistors whose gate input k drives: its uses in the complex stage, and its inverter."""
    def uses(e):
        if e[0] == "in":
            return c.signals[e[1]] == (k, False)
        return uses(e[1]) + uses(e[2])

    return 2 * uses(c.form.expr) + 2 * (k in c.inverted)
