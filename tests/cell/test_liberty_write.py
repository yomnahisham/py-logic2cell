import pytest

from src.cell.characterize import SIDE_RULES, combine
from src.cell.liberty_timing import parse, read_setup
from src.cell.liberty_write import cell_group, library, one_build

NGSPICE = {"version": "ngspice-47", "sha256": "0" * 64, "image": "test"}


def timing(values=None):
    t = values or [[0.01, 0.02], [0.03, 0.04]]
    tables = {k: t for k in ("cell_rise", "cell_fall", "rise_transition", "fall_transition")}
    return dict(cell="x_inv", inputs=["A"], output="Y", ngspice=NGSPICE,
                pins={"A": {"capacitance": 0.0023, "rise_capacitance": 0.0024, "fall_capacitance": 0.0022}},
                arcs=[dict(pin="A", output="Y", sense="negative_unate", index_1=[0.01, 1.5], index_2=[0.0005, 0.18],
                           tables=tables)])


def test_side_rule_is_read_from_the_liberty():
    assert read_setup()["default_arc_mode"] == "worst_edges"
    assert SIDE_RULES["worst_edges"] is max
    assert combine([[[1, 5]], [[2, 3]]], max) == [[2, 5]]


def test_cell_group_round_trips_through_the_reader():
    text = library("t", [timing()], [cell_group(timing(), 3.75, "(!A)", "x_inv")])
    lib = parse(text).all("library")[0]
    cell = lib.all("cell")[0]
    assert cell.args == ["x_inv"] and float(cell.attrs["area"]) == 3.75
    pin_a, pin_y = cell.all("pin")
    assert float(pin_a.attrs["capacitance"]) == pytest.approx(0.0023)
    assert pin_y.attrs["function"] == "(!A)"
    arc = pin_y.all("timing")[0]
    assert arc.attrs["related_pin"] == "A" and arc.attrs["timing_sense"] == "negative_unate"
    rise = next(g for g in arc.groups if g.kind == "cell_rise")
    assert rise.args == ["del_1_2_2"]
    rows = [[float(v) for v in r.split(",")] for r in rise.attrs["values"]]
    assert rows == [[0.01, 0.02], [0.03, 0.04]]
    assert 'lu_table_template ("del_1_2_2")' in text      # a subset grid gets its own template
    assert NGSPICE["sha256"] in text.splitlines()[0]      # the build is stamped at the top


def test_a_table_with_a_hole_is_not_written():
    with pytest.raises(ValueError):
        cell_group(timing([[0.01, None], [0.03, 0.04]]), 3.75, "(!A)")


def test_two_ngspice_builds_are_never_mixed():
    other = dict(timing(), ngspice=dict(NGSPICE, sha256="1" * 64))
    with pytest.raises(ValueError):
        one_build([timing(), other])
