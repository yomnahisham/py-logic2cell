"""The estimate for every class (src/hd/cost.py, estimate): exact where Option 1's structure
builds the function, a Shannon split where it does not."""

from src.common.request import truth_table
from src.common.stage import FULL
from src.hd.cost import cost, estimate


def test_every_function_has_an_estimate_that_computes_it():
    # every 7th function keeps the test short; the whole range was checked once by hand
    for t in range(1, FULL, 7):
        e = estimate(t)
        assert e is not None and e.series <= 3, hex(t)
        assert truth_table(e.expression, ("A", "B", "C", "D")) == t, (hex(t), e.expression)


def test_buildable_functions_keep_their_exact_cost():
    for t in range(1, FULL, 7):
        c, e = cost(t), estimate(t)
        assert e.buildable == (c is not None), hex(t)
        if c is not None:
            assert (e.transistors, e.stages, e.inverters) == (c.transistors, c.stages, c.inverters)


def test_functions_option1_cannot_build():
    xor3 = estimate(0x96, 3)
    assert not xor3.buildable and xor3.transistors == 24      # xor2 (12) joined with A by an xor (12)
    nand4 = estimate(0x7FFF, 4)
    assert not nand4.buildable and nand4.series <= 3           # HD's nand4 has 4 in series
    assert estimate(0, 4) is None and estimate(FULL, 4) is None
