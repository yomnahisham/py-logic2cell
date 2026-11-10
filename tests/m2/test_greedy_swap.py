"""The swap search after the greedy (src/hd/greedy.py --swap): never worse than the greedy, and it finds
the better pair when the greedy's order misses it."""

from src.hd.greedy import greedy, swaps


def cell(name):
    return {"name": name, "area_um2": 1.0}


def table(areas):
    """A fake trial: the total area of a set, from a table over frozensets of names (others: no gain)."""
    return lambda cells: {"total": areas.get(frozenset(c["name"] for c in cells), 100.0)}


def test_swap_finds_what_the_order_misses():
    # a alone helps a little and c helps once a is in, so the greedy keeps {a, c}; {b, c} is better but
    # b alone does not help, so the greedy's order never reaches it. One swap (a -> b) does.
    areas = {frozenset(): 100.0, frozenset("a"): 99.0, frozenset("b"): 100.0, frozenset("c"): 100.0,
             frozenset("ab"): 99.0, frozenset("ac"): 98.0, frozenset("bc"): 90.0}
    trial = table(areas)
    pool = [cell("a"), cell("b"), cell("c")]
    chosen, _, final = greedy(pool, trial, limit=2, log=lambda *_: None)
    assert [c["name"] for c in chosen] == ["a", "c"] and final["total"] == 98.0
    best, _, result = swaps(chosen, [cell("b")], final, trial, log=lambda *_: None)
    assert sorted(c["name"] for c in best) == ["b", "c"] and result["total"] == 90.0


def test_swap_never_worse():
    areas = {frozenset(): 100.0, frozenset("a"): 95.0, frozenset("b"): 97.0}
    trial = table(areas)
    chosen, _, final = greedy([cell("a"), cell("b")], trial, limit=1, log=lambda *_: None)
    best, trace, result = swaps(chosen, [cell("b")], final, trial, log=lambda *_: None)
    assert result["total"] == 95.0 and [c["name"] for c in best] == ["a"]
    assert all(r["decision"] in ("kept", "swapped") for r in trace)
