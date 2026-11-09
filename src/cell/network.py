"""Single-stage CMOS network: build, switch-level check, Euler ordering.

A network is ("in", name), ("s", [...]) for series or ("p", [...]) for parallel.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from itertools import islice, permutations, product
import re
import sys

from src.common.stage import FULL, N, expression, forms, support, widen

MAX_SERIES = 3


class NetworkError(ValueError):
    pass


def parse(expression: str):
    """Parse into ("var", x), ("not", t), ("and"|"or"|"xor", [...]). ! binds tightest, then &, ^, |."""
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\S", expression) + [None]
    pos = 0

    def take(expected=None):
        nonlocal pos
        token = tokens[pos]
        if expected and token != expected:
            raise NetworkError(f"expected {expected!r}, got {token!r}")
        pos += 1
        return token

    def chain(op, symbol, operand):
        def rule():
            terms = [operand()]
            while tokens[pos] == symbol:
                take()
                terms.append(operand())
            return terms[0] if len(terms) == 1 else (op, terms)
        return rule

    def unary():
        if tokens[pos] == "!":
            take()
            return ("not", unary())
        if tokens[pos] == "(":
            take()
            tree = expr()
            take(")")
            return tree
        token = take()
        if token is None or not re.match(r"[A-Za-z_]", token):
            raise NetworkError(f"expected an input, got {token!r}")
        return ("var", token)

    expr = chain("or", "|", chain("xor", "^", chain("and", "&", unary)))
    tree = expr()
    if tokens[pos] is not None:
        raise NetworkError(f"unexpected {tokens[pos]!r}")
    return tree


def pull_down(tree):
    """Pull-down of Y = tree. Pushes NOTs down to the inputs; every input must end up inverted."""
    def walk(t, negated):
        if t[0] == "var":
            if not negated:
                raise NetworkError(f"{t[1]} is not inverted, needs more than one stage")
            return ("in", t[1])
        if t[0] == "not":
            return walk(t[1], not negated)
        if t[0] == "xor":
            raise NetworkError("xor needs more than one stage")
        series = (t[0] == "or") != negated
        return ("s" if series else "p", [walk(c, negated) for c in t[1]])
    return flatten(walk(tree, False))


def flatten(net):
    if net[0] == "in":
        return net
    children = []
    for child in map(flatten, net[1]):
        children += child[1] if child[0] == net[0] else [child]
    return children[0] if len(children) == 1 else (net[0], children)


def dual(net):
    if net[0] == "in":
        return net
    return ("p" if net[0] == "s" else "s", [dual(c) for c in net[1]])


def depth(net) -> int:
    """Most transistors in series."""
    if net[0] == "in":
        return 1
    d = [depth(c) for c in net[1]]
    return sum(d) if net[0] == "s" else max(d)


@dataclass(frozen=True)
class Fet:
    kind: str  # "n" or "p"
    gate: str
    a: str     # output side
    b: str     # supply side
    w: float | None = field(default=None, compare=False)    # width (um), None for the cell's default


def expand(net, kind, top, bottom, count):
    if net[0] == "in":
        return [Fet(kind, net[1], top, bottom)]
    if net[0] == "p":
        return [f for c in net[1] for f in expand(c, kind, top, bottom, count)]
    fets = []
    for i, child in enumerate(net[1]):
        if i == len(net[1]) - 1:
            lower = bottom
        else:
            count[0] += 1
            lower = f"{kind}{count[0]}"
        fets += expand(child, kind, top, lower, count)
        top = lower
    return fets


@dataclass(frozen=True)
class Stage:
    inputs: tuple[str, ...]
    output: str
    fets: tuple[Fet, ...]


def build_stage(inputs, output, expression) -> Stage:
    pdn = pull_down(parse(expression))
    pun = dual(pdn)
    if max(depth(pdn), depth(pun)) > MAX_SERIES:
        raise NetworkError(f"{max(depth(pdn), depth(pun))} transistors in series, max {MAX_SERIES}")
    fets = expand(pdn, "n", output, "VGND", [0]) + expand(pun, "p", output, "VPWR", [0])
    return Stage(tuple(inputs), output, tuple(fets))


def reorders(net):
    """The network with the transistors of each series stack in every order (Uehara and
    vanCleemput's gate reordering). The function stays the same; the order changes which
    nodes are internal, and so the Euler paths and the netlist the cell matches."""
    if net[0] == "in":
        return [net]
    choices = [reorders(c) for c in net[1]]
    if net[0] == "p":
        return [("p", list(cs)) for cs in product(*choices)]
    out = []
    for perm in permutations(range(len(choices))):
        out += [("s", list(cs)) for cs in product(*(choices[i] for i in perm))]
    return out


def stage_variants(inputs, output, expression) -> list[Stage]:
    """build_stage, then every reordering of the series stacks; the expression's own order first."""
    first = build_stage(inputs, output, expression)
    pdn = pull_down(parse(expression))
    out, seen = [first], {frozenset(first.fets)}
    for down in reorders(pdn):
        for up in reorders(dual(pdn)):
            fets = expand(down, "n", output, "VGND", [0]) + expand(up, "p", output, "VPWR", [0])
            if frozenset(fets) not in seen:
                seen.add(frozenset(fets))
                out.append(Stage(tuple(inputs), output, tuple(fets)))
    return out


def switch_check(stage: Stage, table: int) -> list[str]:
    """Every input combination with ideal switches. Returns the errors found."""
    errors = []
    for i in range(1 << len(stage.inputs)):
        value = {name: i >> k & 1 for k, name in enumerate(stage.inputs)}
        parent = {}

        def find(x):
            while parent.get(x, x) != x:
                x = parent[x]
            return x

        for f in stage.fets:
            if value[f.gate] == (f.kind == "n"):
                parent[find(f.a)] = find(f.b)
        y, vpwr, vgnd = find(stage.output), find("VPWR"), find("VGND")
        want = table >> i & 1
        bits = f"{i:0{len(stage.inputs)}b}"
        if vpwr == vgnd:
            errors.append(f"{bits}: VPWR shorted to VGND")
        elif y not in (vpwr, vgnd):
            errors.append(f"{bits}: output floats")
        elif (y == vpwr) != want:
            errors.append(f"{bits}: output {int(y == vpwr)}, expected {want}")
    return errors


# Multi-stage cells. One stage computes Y = !G with G monotone in its gate signals. A function that
# is not negative unate gets those signals from more stages: inverted inputs, and an output inverter.

def split(inputs, output, table: int, max_series: int = MAX_SERIES) -> list[tuple[tuple[str, ...], str, str]]:
    """Stages (inputs, output, expression), in signal order, with the fewest transistors: input
    inverters, then one complex stage over the inputs and their inverses, then an output inverter
    if that is smaller. The complex stage is the smallest form of stage.py over its signals."""
    n, t = len(inputs), widen(table, len(inputs))
    best = None
    for out_inverter in (False, True):
        # the complex stage computes !G; G = !Y without an output inverter, G = Y with one
        g = t if out_inverter else FULL ^ t
        signals = []    # (input index, inverted): G rises with the input, or with its inverse
        for k in support(t):
            rises = any(not g >> i & 1 and g >> (i | 1 << k) & 1 for i in range(1 << N) if not i >> k & 1)
            falls = any(g >> i & 1 and not g >> (i | 1 << k) & 1 for i in range(1 << N) if not i >> k & 1)
            signals += [(k, False)] * rises + [(k, True)] * falls
        if len(signals) > N:
            continue
        # G over the signals: the smallest monotone function that agrees with g whenever every
        # inverse really is the inverse of its input
        value = lambda i, k, inv: (i >> k & 1) ^ inv
        on = [i for i in range(1 << N) if g >> i & 1]
        over = sum(1 << m for m in range(1 << len(signals))
                   if any(all(value(i, k, inv) <= (m >> j & 1) for j, (k, inv) in enumerate(signals)) for i in on))
        form = forms(max_series).get(widen(over, len(signals)))
        if form is None:
            continue
        names = [inputs[k] + "_b" if inv else inputs[k] for k, inv in signals]
        inverted = [inputs[k] for k, inv in signals if inv]
        size = 2 * form.size + 2 * len(inverted) + 2 * out_inverter
        stages = [((x,), x + "_b", f"!{x}") for x in inverted]
        middle = output + "_b" if out_inverter else output
        stages.append((tuple(names), middle, expression(form, names)))
        if out_inverter:
            stages.append(((middle,), output, f"!{middle}"))
        if best is None or (size, len(stages)) < best[0]:
            best = ((size, len(stages)), stages)
    if best is None:
        raise NetworkError("no split into stages of at most 4 signals and 3 transistors in series")
    return best[1]


@dataclass(frozen=True)
class Cell:
    stages: tuple[Stage, ...]   # in signal order
    flat: Stage                 # every transistor as one network, for ordering, layout and the schematic


def cell_variants(inputs, output, table: int, limit: int = 64) -> list[Cell]:
    """The stages of split(), each in every series order, as cells."""
    return cells_of(inputs, output, split(inputs, output, table), limit)


def text(tree) -> str:
    """A parse() tree written back as an expression."""
    if tree[0] == "var":
        return tree[1]
    wrap = lambda t: f"({text(t)})" if t[0] in ("and", "or", "xor") else text(t)
    if tree[0] == "not":
        return "!" + wrap(tree[1])
    return {"and": " & ", "or": " | ", "xor": " ^ "}[tree[0]].join(wrap(c) for c in tree[1])


def names_in(tree) -> set:
    return {tree[1]} if tree[0] == "var" else names_in(tree[1]) if tree[0] == "not" else set().union(*map(names_in, tree[1]))


def operand_splits(inputs, output, expression, m: str | None = None) -> list[list[tuple[tuple[str, ...], str, str]]]:
    """A one-stage function too dense to draw (handout step 2: otherwise decompose it), as three stages:
    one operand Q of its top operator computed on its own (!Q, then an inverter: Q on net <output>_m),
    and the rest as a stage that takes <output>_m (or m) in place of Q. One split per operand of more than one
    input. Each stage still has at most 3 transistors in series, or the split is left out."""
    tree = parse(expression)
    if tree[0] != "not" or tree[1][0] not in ("and", "or"):
        return []
    op, kids = tree[1]
    m = m or output + "_m"
    out = []
    for i, q in enumerate(kids):
        if len(names_in(q)) < 2:
            continue
        rest = (op, kids[:i] + [("var", m)] + kids[i + 1:])
        stages = [(tuple(x for x in inputs if x in names_in(q)), m + "_b", f"!({text(q)})"),
                  ((m + "_b",), m, f"!{m}_b"),
                  (tuple(x for x in inputs if x in names_in(rest)) + (m,), output, f"!({text(rest)})")]
        try:
            for stage in stages:
                build_stage(*stage)
        except NetworkError:
            continue
        out.append(stages)
    return out


def cells_of(inputs, output, stages, limit: int = 64) -> list[Cell]:
    """Stages (inputs, output, expression), each in every series order, as cells. The internal nodes of
    the stages are renumbered so that they stay apart in the flat network."""
    choices = []
    for stage_inputs, stage_output, expr in stages:
        choices.append(stage_variants(stage_inputs, stage_output, expr))
    out = []
    for combo in islice(product(*choices), limit):
        count, stages = {"n": 0, "p": 0}, []
        for stage in combo:
            rename = {}
            for f in stage.fets:
                for node in (f.a, f.b):
                    if node[0] in "np" and node[1:].isdigit() and node not in rename:
                        count[node[0]] += 1
                        rename[node] = f"{node[0]}{count[node[0]]}"
            fets = tuple(Fet(f.kind, f.gate, rename.get(f.a, f.a), rename.get(f.b, f.b), f.w) for f in stage.fets)
            stages.append(Stage(stage.inputs, stage.output, fets))
        flat = Stage(tuple(inputs), output, tuple(f for s in stages for f in s.fets))
        out.append(Cell(tuple(stages), flat))
    return out


def cell_check(cell: Cell, table: int) -> list[str]:
    """Every input combination with ideal switches, stage by stage. Returns the errors found."""
    errors, inputs = [], cell.flat.inputs
    for i in range(1 << len(inputs)):
        value = {name: i >> k & 1 for k, name in enumerate(inputs)}
        bits = f"{i:0{len(inputs)}b}"
        for stage in cell.stages:
            parent = {}

            def find(x):
                while parent.get(x, x) != x:
                    x = parent[x]
                return x

            for f in stage.fets:
                if value[f.gate] == (f.kind == "n"):
                    parent[find(f.a)] = find(f.b)
            y, vpwr, vgnd = find(stage.output), find("VPWR"), find("VGND")
            if vpwr == vgnd:
                errors.append(f"{bits}: VPWR shorted to VGND in the stage of {stage.output}")
                break
            if y not in (vpwr, vgnd):
                errors.append(f"{bits}: {stage.output} floats")
                break
            value[stage.output] = int(y == vpwr)
        else:
            if value[cell.flat.output] != table >> i & 1:
                errors.append(f"{bits}: output {value[cell.flat.output]}, expected {table >> i & 1}")
    return errors


@dataclass(frozen=True)
class Order:
    gates: tuple[str, ...]
    n_nodes: tuple[str, ...]
    p_nodes: tuple[str, ...]
    n_fets: tuple = field(default=(), compare=False)     # the transistor under each gate, None at a break
    p_fets: tuple = field(default=(), compare=False)


BREAK = "|"         # in Order.gates: a diffusion break instead of a gate, in the rows that change net there
MAX_BREAKS = 3


def euler_order(stage: Stage) -> Order | None:
    """Common Euler path of both rows with the fewest contacts, or None if the rows need a diffusion break."""
    orders = euler_orders(stage, max_breaks=0)
    return orders[0] if orders else None


def euler_orders(stage: Stage, max_breaks: int = MAX_BREAKS) -> list[Order]:
    """Every common Euler path of both rows, from every pair of start nets, fewest contacts first.
    The layout takes the first one it can route. Where no path covers every transistor, the rows
    are cut by diffusion breaks (BREAK in the gate order), as few as will do, at most max_breaks:
    each piece is a common path of its own, and the two sides of a break have their own columns."""
    n = [f for f in stage.fets if f.kind == "n"]
    p = [f for f in stage.fets if f.kind == "p"]
    # a gate with more fingers in one row than the other (unequal folding, build.stacked) gets columns
    # where only that row has a transistor and the other row's diffusion runs on under it ("passes").
    # With equal counts, as every single-finger cell has, there are none and the search is unchanged.
    extra = {g: Counter(f.gate for f in n)[g] - Counter(f.gate for f in p)[g] for g in {f.gate for f in n + p}}
    if any(Counter(f.gate for f in n)[g] == 0 or Counter(f.gate for f in p)[g] == 0 for g in extra):
        return []
    found = {}
    # the fingers of one folded transistor are the same device: a path takes them in index order, since
    # any other order gives the same gates and nodes (twins_*[i]: the earlier fingers identical to i)
    twins_n = [[k for k in range(i) if (n[k], n[k].w) == (n[i], n[i].w)] for i in range(len(n))]
    twins_p = [[k for k in range(j) if (p[k], p[k].w) == (p[j], p[j].w)] for j in range(len(p))]

    def other(f, node):
        return f.b if f.a == node else f.a if f.b == node else None

    def walk(at_n, at_p, used_n, used_p, gates, n_nodes, p_nodes, breaks, fets=((), ())):
        if used_n == (1 << len(n)) - 1 and used_p == (1 << len(p)) - 1:
            order = Order(tuple(gates), tuple(n_nodes), tuple(p_nodes), *fets)
            found.setdefault(order, len(found))
            return
        for i, fn in enumerate(n):
            next_n = other(fn, at_n)
            if used_n >> i & 1 or next_n is None or any(not used_n >> k & 1 for k in twins_n[i]):
                continue
            for j, fp in enumerate(p):
                next_p = other(fp, at_p)
                if used_p >> j & 1 or fp.gate != fn.gate or next_p is None or any(not used_p >> k & 1 for k in twins_p[j]):
                    continue
                walk(next_n, next_p, used_n | 1 << i, used_p | 1 << j,
                     gates + [fn.gate], n_nodes + [next_n], p_nodes + [next_p], breaks,
                     (fets[0] + (fn,), fets[1] + (fp,)))
        # one row alone, while that row still has more fingers of the gate left than the other
        left = lambda used, fs, g: sum(1 for k, f in enumerate(fs) if f.gate == g and not used >> k & 1)
        for i, fn in enumerate(n):
            next_n = other(fn, at_n)
            if (extra[fn.gate] > 0 and not used_n >> i & 1 and next_n is not None
                    and not any(not used_n >> k & 1 for k in twins_n[i])
                    and left(used_n, n, fn.gate) > left(used_p, p, fn.gate)):
                walk(next_n, at_p, used_n | 1 << i, used_p, gates + [fn.gate], n_nodes + [next_n], p_nodes + [at_p],
                     breaks, (fets[0] + (fn,), fets[1] + (None,)))
        for j, fp in enumerate(p):
            next_p = other(fp, at_p)
            if (extra[fp.gate] < 0 and not used_p >> j & 1 and next_p is not None
                    and not any(not used_p >> k & 1 for k in twins_p[j])
                    and left(used_p, p, fp.gate) > left(used_n, n, fp.gate)):
                walk(at_n, next_p, used_n, used_p | 1 << j, gates + [fp.gate], n_nodes + [at_n], p_nodes + [next_p],
                     breaks, (fets[0] + (None,), fets[1] + (fp,)))
        if breaks and gates and gates[-1] != BREAK:
            for start_n, start_p in starts(used_n, used_p):
                walk(start_n, start_p, used_n, used_p, gates + [BREAK], n_nodes + [start_n],
                     p_nodes + [start_p], breaks - 1, (fets[0] + (None,), fets[1] + (None,)))

    def starts(used_n, used_p):
        left_n = sorted({x for i, f in enumerate(n) if not used_n >> i & 1 for x in (f.a, f.b)})
        left_p = sorted({x for j, f in enumerate(p) if not used_p >> j & 1 for x in (f.a, f.b)})
        return product(left_n, left_p)

    for breaks in range(max_breaks + 1):
        for start_n, start_p in starts(0, 0):
            walk(start_n, start_p, 0, 0, [], [start_n], [start_p], breaks)
        if found:
            break
    return sorted(found, key=lambda order: (contacts(order), found[order]))


def stack_depths(stage: Stage) -> dict[int, int]:
    """For each transistor (by index in stage.fets), the number of transistors in series on the longest
    path from the output to the supply that runs through it."""
    def longest(fets, start, forward):
        memo = {}
        def go(node):
            if node not in memo:
                memo[node] = max((1 + go(f.b if forward else f.a) for f in fets if (f.a if forward else f.b) == node),
                                 default=0)
            return memo[node]
        return go
    out = {}
    for kind in "np":
        fets = [f for f in stage.fets if f.kind == kind]
        down, up = longest(fets, None, True), longest(fets, None, False)
        for i, f in enumerate(stage.fets):
            if f.kind == kind:
                out[i] = up(f.a) + 1 + down(f.b)
    return out


def joined(gates, nodes, fets=()) -> set:
    """Columns just after a break where the row has the same net on both sides. That row is not cut:
    its diffusion runs on through the break, as HD's a21o_1 keeps its NMOS row, so the column is the
    same diffusion as the one before it. The same holds where the row passes under a gate with no
    transistor of its own (fets[i] None at a gate: the other row's extra finger, unequal folding)."""
    passes = {i for i, g in enumerate(gates) if g != BREAK and fets and fets[i] is None}
    return {i + 1 for i, g in enumerate(gates) if (g == BREAK or i in passes) and nodes[i] == nodes[i + 1]}


def passes(order: "Order", row: str) -> set:
    """Gate columns where this row has no transistor: the poly stops at the middle band."""
    fets = order.n_fets if row == "n" else order.p_fets
    return {i for i, g in enumerate(order.gates) if g != BREAK and fets and fets[i] is None}


def contacts(order: Order) -> int:
    """Diffusions that need a contact. An internal node that shows up once is just shared diffusion."""
    total = 0
    for nodes, fets in ((order.n_nodes, order.n_fets), (order.p_nodes, order.p_fets)):
        skip = joined(order.gates, nodes, fets)
        kept = [net for i, net in enumerate(nodes) if i not in skip]
        for net in kept:
            internal = net[0] in "np" and net[1:].isdigit()
            total += not (internal and kept.count(net) == 1)
    return total


def schematic(stage: Stage, name: str, wn: float, wp: float, l: float = 0.15, widths: dict | None = None) -> str:
    """SPICE subcircuit with HD's port order: inputs, VGND VNB VPB VPWR, output.
    A transistor's own width comes first, then widths per (kind, gate), then wn and wp."""
    widths = widths or {}
    lines = [f".subckt {name} {' '.join(stage.inputs)} VGND VNB VPB VPWR {stage.output}"]
    for i, f in enumerate(stage.fets):
        if f.kind == "n":
            w = f.w or widths.get(("n", f.gate), wn)
            lines.append(f"X{i} {f.a} {f.gate} {f.b} VNB sky130_fd_pr__nfet_01v8 w={w:g} l={l:g}")
        else:
            w = f.w or widths.get(("p", f.gate), wp)
            lines.append(f"X{i} {f.a} {f.gate} {f.b} VPB sky130_fd_pr__pfet_01v8_hvt w={w:g} l={l:g}")
    return "\n".join(lines + [".ends", ""])


if __name__ == "__main__":
    from src.common.request import RequestError, read_request

    try:
        request = read_request(sys.argv[1])
        stage = build_stage(request.inputs, request.output, request.expression)
    except (RequestError, NetworkError) as error:
        print(f"refused: {error}")
        sys.exit(1)
    errors = switch_check(stage, request.truth_table)
    print("\n".join(errors) or f"switch level: pass ({1 << len(stage.inputs)} combinations)")
    order = euler_order(stage)
    if order:
        print("gates ", *order.gates)
        print("n row ", *order.n_nodes)
        print("p row ", *order.p_nodes)
    else:
        print("no common Euler path")
    print(schematic(stage, request.name, 0.65, 1.0), end="")
    sys.exit(1 if errors or not order else 0)
