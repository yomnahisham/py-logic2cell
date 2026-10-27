import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.cell.network import NetworkError, build_stage, euler_order, schematic, switch_check
from src.common.request import truth_table

ROOT = Path(__file__).resolve().parents[2]
BROKEN = json.loads((ROOT / "tests/broken/networks.json").read_text())

# single-stage functions from Table 6 of the option 1 handout
SINGLE_STAGE = [
    ("A", "!A"), ("AB", "!(A & B)"), ("AB", "!(A | B)"), ("ABC", "!(A & B & C)"),
    ("ABC", "!(A | B | C)"), ("ABC", "!((A & B) | C)"), ("ABC", "!((A | B) & C)"),
    ("ABCD", "!((A & B) | (C & D))"), ("ABCD", "!((A | B) & (C | D))"),
    ("ABCD", "!(A & (B | (C & D)))"), ("ABCD", "!(A | (B & (C | D)))"),
    ("ABCD", "!((C&D) | (A&B&(C|D)))"), ("AB", "!A | !B"),
]


@pytest.mark.parametrize(("inputs", "expression"), SINGLE_STAGE)
def test_single_stage(inputs, expression):
    stage = build_stage(tuple(inputs), "Y", expression)
    assert switch_check(stage, truth_table(expression, tuple(inputs))) == []
    order = euler_order(stage)
    assert order is not None
    assert len(order.n_nodes) == len(order.p_nodes) == len(order.gates) + 1


@pytest.mark.parametrize("expression", ["A & B", "A ^ B", "!(A & B & C & D)", "(A & !C) | (B & C)"])
def test_multi_stage_refused(expression):
    with pytest.raises(NetworkError):
        build_stage(("A", "B", "C", "D"), "Y", expression)


def test_nand2_like_hd():
    stage = build_stage(("A", "B"), "Y", "!(A & B)")
    assert euler_order(stage).n_nodes == ("VGND", "n1", "Y")
    assert schematic(stage, "x", 0.65, 1.0).startswith(".subckt x A B VGND VNB VPB VPWR Y\n")


@pytest.mark.parametrize("case", BROKEN, ids=[c["name"] for c in BROKEN])
def test_broken_network_fails(case):
    inputs = tuple(case["inputs"])
    stage = build_stage(inputs, "Y", case["expression"])
    if "delete" in case:
        kind, gate = case["delete"]
        gone = next(f for f in stage.fets if f.kind == kind and f.gate == gate)
        stage = replace(stage, fets=tuple(f for f in stage.fets if f is not gone))
    table = int(case["truth_table"], 16) if "truth_table" in case else truth_table(case["expression"], inputs)
    assert switch_check(stage, table) != []
