"""Single-stage CMOS network: build, switch-level check, Euler ordering.

A network is ("in", name), ("s", [...]) for series or ("p", [...]) for parallel.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations, product
import re
import sys

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


@dataclass(frozen=True)
class Order:
    gates: tuple[str, ...]
    n_nodes: tuple[str, ...]
    p_nodes: tuple[str, ...]


def euler_order(stage: Stage) -> Order | None:
    """Common Euler path of both rows with the fewest contacts, or None if the rows need a diffusion break."""
    orders = euler_orders(stage)
    return orders[0] if orders else None


def euler_orders(stage: Stage) -> list[Order]:
    """Every common Euler path of both rows, from every pair of start nets, fewest contacts first.
    The layout takes the first one it can route."""
    n = [f for f in stage.fets if f.kind == "n"]
    p = [f for f in stage.fets if f.kind == "p"]
    if len(n) != len(p):
        return []
    found = {}

    def other(f, node):
        return f.b if f.a == node else f.a if f.b == node else None

    def walk(at_n, at_p, used_n, used_p, gates, n_nodes, p_nodes):
        if len(gates) == len(n):
            order = Order(tuple(gates), tuple(n_nodes), tuple(p_nodes))
            found.setdefault(order, len(found))
            return
        for i, fn in enumerate(n):
            next_n = other(fn, at_n)
            if used_n >> i & 1 or next_n is None:
                continue
            for j, fp in enumerate(p):
                next_p = other(fp, at_p)
                if used_p >> j & 1 or fp.gate != fn.gate or next_p is None:
                    continue
                walk(next_n, next_p, used_n | 1 << i, used_p | 1 << j,
                     gates + [fn.gate], n_nodes + [next_n], p_nodes + [next_p])

    starts_n = sorted({x for f in n for x in (f.a, f.b)})
    starts_p = sorted({x for f in p for x in (f.a, f.b)})
    for start_n, start_p in product(starts_n, starts_p):
        walk(start_n, start_p, 0, 0, [], [start_n], [start_p])
    return sorted(found, key=lambda order: (contacts(order), found[order]))


def contacts(order: Order) -> int:
    """Diffusions that need a contact. An internal node that shows up once is just shared diffusion."""
    total = 0
    for nodes in (order.n_nodes, order.p_nodes):
        for net in nodes:
            internal = net[0] in "np" and net[1:].isdigit()
            total += not (internal and nodes.count(net) == 1)
    return total


def schematic(stage: Stage, name: str, wn: float, wp: float, l: float = 0.15, widths: dict | None = None) -> str:
    """SPICE subcircuit with HD's port order: inputs, VGND VNB VPB VPWR, output.
    widths overrides wn and wp per (kind, gate)."""
    widths = widths or {}
    lines = [f".subckt {name} {' '.join(stage.inputs)} VGND VNB VPB VPWR {stage.output}"]
    for i, f in enumerate(stage.fets):
        if f.kind == "n":
            w = widths.get(("n", f.gate), wn)
            lines.append(f"X{i} {f.a} {f.gate} {f.b} VNB sky130_fd_pr__nfet_01v8 w={w:g} l={l:g}")
        else:
            w = widths.get(("p", f.gate), wp)
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
