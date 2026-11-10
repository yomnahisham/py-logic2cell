"""The fallback of handout step 2 ("otherwise decompose the function"): a one-stage function whose layout
cannot be drawn, split into stages. Every split must still compute the function."""

import pytest

from src.cell.network import cell_check, cells_of, operand_splits, text, parse
from src.common.request import truth_table

FUNCTIONS = ["!((C & D) | ((A | B) & (C | D)))",    # f011f
             "!(D & ((A & B) | (C & (A | B))))",    # f17ff
             "!(D | ((A | B) & (C | (A & B))))"]    # f0017


@pytest.mark.parametrize("expression", FUNCTIONS)
def test_every_split_gives_the_function(expression):
    inputs = ("A", "B", "C", "D")
    splits = operand_splits(inputs, "Y", expression)
    assert splits
    for stages in splits:
        assert len(stages) == 3
        for cell in cells_of(inputs, "Y", stages)[:8]:
            assert cell_check(cell, truth_table(expression, inputs)) == []


def test_text_round_trip():
    for e in FUNCTIONS + ["!A", "A ^ B", "(A & !C) | (B & C)"]:
        assert truth_table(text(parse(e)), ("A", "B", "C", "D")) == truth_table(e, ("A", "B", "C", "D"))


def test_broken_split_is_caught():
    # a split whose last stage drops the inverter's output must fail the switch-level check
    inputs = ("A", "B", "C", "D")
    stages = operand_splits(inputs, "Y", FUNCTIONS[0])[0]
    broken = stages[:2] + [(stages[2][0], "Y", stages[2][2].replace("Y_m", "Y_m_b"))]
    broken[2] = (tuple(x for x in broken[2][0] if x != "Y_m") + ("Y_m_b",), "Y", broken[2][2])
    cell = cells_of(inputs, "Y", broken)[0]
    assert cell_check(cell, truth_table(FUNCTIONS[0], inputs))


def test_splits_nest():
    # the fallback splits the largest stage again while nothing can be drawn; each level must still compute
    # the function, with the new net named apart from the last one
    inputs = ("A", "B", "C", "D")
    table = truth_table(FUNCTIONS[0], inputs)
    stages = operand_splits(inputs, "Y", FUNCTIONS[0])[0]
    k = max(range(len(stages)), key=lambda i: len(stages[i][2]))
    deeper = operand_splits(*stages[k], m=f"{stages[k][1]}_m2")
    assert deeper
    nested = stages[:k] + deeper[0] + stages[k + 1:]
    assert len({o for _, o, _ in nested}) == len(nested)
    assert cell_check(cells_of(inputs, "Y", nested)[0], table) == []
