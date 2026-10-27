import pytest

from src.cell.network import build_stage, switch_check
from src.common.request import truth_table
from src.common.stage import expression, forms, single_stage

ABCD = ("A", "B", "C", "D")


def test_every_monotone_function_has_a_form():
    assert len(forms(12, 12)) == 166          # 168 monotone 4-input functions, minus the two constants


@pytest.mark.parametrize(("written", "transistors"), [
    ("!A", 2), ("!(A & B)", 4), ("!A | !B", 4), ("!(A | B | C)", 6), ("!((A & B) | C)", 6),
    ("!((A & B) | (C & D))", 8), ("!(A & (B | (C & D)))", 8), ("!((C&D) | (A&B&(C|D)))", 12),
    ("!((A & !A) | B)", 2),
])
def test_minimal_form_builds_and_checks(written, transistors):
    table = truth_table(written, ABCD)
    form = single_stage(table)
    assert 2 * form.size == transistors
    stage = build_stage(ABCD, "Y", expression(form, list(ABCD)))
    assert switch_check(stage, table) == []


@pytest.mark.parametrize("written", ["A & B", "A ^ B", "!(A & B & C & D)", "(A & !C) | (B & C)", "!A & B"])
def test_not_one_stage(written):
    assert single_stage(truth_table(written, ABCD)) is None


def test_fewer_inputs():
    assert expression(single_stage(0x7, 2), ["A", "B"]) == "!(A & B)"
