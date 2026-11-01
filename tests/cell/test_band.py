from src.cell.band import Item, Stats, solutions


def test_band_backtracks_where_greedy_would_not():
    a = Item("A", "pad", 0.165, gates=(0.0, 0.0), reach=1.0)    # wants x = 0
    b = Item("B", "pad", 0.165, gates=(0.2, 0.2), reach=0.2)    # must sit in 0 .. 0.4
    found = next(solutions([a, b], lambda p, q: 0.5, 0.005, 0.17, False, 1000, Stats()))
    assert abs(found[0] - found[1]) >= 0.5 - 1e-9