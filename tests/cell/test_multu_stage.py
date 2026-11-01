"""Multi-stage cells: the split into stages, the stage-by-stage switch check, diffusion breaks."""

from dataclasses import replace

import pytest

from src.cell.network import BREAK, Cell, cell_check, cell_variants, euler_orders
from src.common.request import truth_table

# Table 6 functions that need more than one stage: (inputs, expression, stages)
MULTI_STAGE = [
    ("AB", "A & B", 2), ("ABC", "(A & B) | C", 2), ("ABC", "(A & !C) | (B & C)", 3),
    ("ABC", "(A & B) | (C & (A | B))", 2), ("AB", "A ^ B", 3), ("ABCD", "(C&D) | (A&B&(C|D))", 2),
]


@pytest.mark.parametrize(("inputs", "expression", "stages"), MULTI_STAGE)
def test_split_computes_the_function(inputs, expression, stages):
    table = truth_table(expression, tuple(inputs))
    cells = cell_variants(tuple(inputs), "Y", table)
    assert all(len(c.stages) == stages for c in cells)
    assert all(cell_check(c, table) == [] for c in cells)


@pytest.mark.parametrize(("inputs", "expression", "stages"), MULTI_STAGE)
def test_every_order_uses_every_transistor(inputs, expression, stages):
    cell = cell_variants(tuple(inputs), "Y", truth_table(expression, tuple(inputs)))[0]
    orders = euler_orders(cell.flat)
    n = sum(f.kind == "n" for f in cell.flat.fets)
    assert orders
    assert all(len([g for g in o.gates if g != BREAK]) == n for o in orders)


def test_mux2_needs_a_break():
    table = truth_table("(A & !C) | (B & C)", ("A", "B", "C"))
    cells = cell_variants(("A", "B", "C"), "Y", table)
    assert min(o.gates.count(BREAK) for c in cells for o in euler_orders(c.flat)) == 1


def test_broken_cell_missing_pullup():
    """The stage-by-stage check must catch a transistor missing from a later stage."""
    table = truth_table("A & B", ("A", "B"))
    cell = cell_variants(("A", "B"), "Y", table)[0]
    last = cell.stages[-1]
    gone = next(f for f in last.fets if f.kind == "p")
    broken = Cell(cell.stages[:-1] + (replace(last, fets=tuple(f for f in last.fets if f is not gone)),), cell.flat)
    assert cell_check(broken, table) != []