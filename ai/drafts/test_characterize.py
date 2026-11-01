"""DRAFT, written by the assistant: AGENTS.md forbids it to edit tests/. A member reviews this file and,
if it is right, moves it to tests/cell/test_characterize.py.

The expected values below are copied from sky130_fd_sc_hd__tt_025C_1v80.lib (header and nand2_1) and
from the handout (section 5: SA = SB = 0.26 um for inv_1). Expected values live only in tests (rule 4).
"""

import json
from pathlib import Path

import pytest

from src.cell.arcs import arcs
from src.cell.characterize import pick, ramp_time
from src.cell.liberty_timing import parse, read_cell, read_setup

ROOT = Path(__file__).resolve().parents[2]


# Step 1: the Liberty setup
def test_setup_is_read_from_the_liberty():
    s = read_setup()
    assert s["input_threshold_pct_rise"] == s["input_threshold_pct_fall"] == 50
    assert s["output_threshold_pct_rise"] == s["output_threshold_pct_fall"] == 50
    assert s["slew_lower_threshold_pct_rise"] == s["slew_lower_threshold_pct_fall"] == 20
    assert s["slew_upper_threshold_pct_rise"] == s["slew_upper_threshold_pct_fall"] == 80
    assert s["slew_derate_from_library"] == 1.0
    assert s["nom_voltage"] == 1.8 and s["nom_temperature"] == 25


def test_nand2_tables_and_capacitance():
    c = read_cell("nand2_1")
    assert c.inputs == ["A", "B"] and c.output == "Y"
    a = next(x for x in c.arcs if x.pin == "A")
    assert a.sense == "negative_unate"
    t = a.tables["cell_fall"]
    assert len(t["index_1"]) == len(t["index_2"]) == 7
    assert t["index_1"][0] == 0.01 and t["index_1"][-1] == 1.5
    assert t["index_2"][0] == 0.0005
    assert c.capacitance["A"]["capacitance"] == pytest.approx(0.002315)


def test_parser_handles_continued_values():
    g = parse('cell ("x") { pin ("Y") { timing () { cell_rise ("t") { index_1 ("1, 2"); \\\n'
              'values ("1, 2", \\\n "3, 4"); } } } }')
    table = g.all("cell")[0].all("pin")[0].all("timing")[0].all("cell_rise")[0]
    assert table.attrs["values"] == ["1, 2", "3, 4"]


# Step 3: arcs from the truth table
def test_nand2_arcs():
    out = arcs(["A", "B"], 0x7)
    assert [(a.pin, a.sense) for a in out] == [("A", "negative_unate"), ("B", "negative_unate")]
    assert out[0].settings[0].side == {"B": 1}


def test_a22oi_has_three_side_settings():
    out = arcs(["A1", "A2", "B1", "B2"], 0x0777)     # !((A1 & A2) | (B1 & B2))
    a1 = next(a for a in out if a.pin == "A1")
    assert len(a1.settings) == 3


def test_xor_is_non_unate_with_four_edge_pairs():
    a = arcs(["A", "B"], 0x6)[0]
    assert a.sense == "non_unate"
    assert {(i, o) for i, o, _ in a.edges()} == {("rise", "rise"), ("rise", "fall"), ("fall", "rise"), ("fall", "fall")}


def test_pin_that_does_not_matter_has_no_arc():
    assert [a.pin for a in arcs(["A", "B"], 0x5)] == ["A"]      # Y = !A


# Steps 4-5: the ramp and the grid
def test_ramp_is_the_slew_over_the_threshold_window():
    s = read_setup()
    assert ramp_time(0.06, s, "rise") == pytest.approx(0.1)
    assert ramp_time(0.06, s, "rise", full_ramp=True) == 0.06     # the broken case


def test_capacitance_window_is_the_input_slew_window():
    from src.cell.characterize import TD, window
    s = read_setup()
    assert window(1.0, s, "rise") == pytest.approx((TD + 0.2, TD + 0.8))
    assert window(1.0, s, "fall") == pytest.approx((TD + 0.2, TD + 0.8))   # passes 80% first, then 20%


def test_pick_keeps_both_ends():
    assert pick([1, 2, 3, 4, 5, 6, 7], 5) == [1, 3, 4, 5, 7]
    assert pick([1, 2, 3], None) == [1, 2, 3]


# Step 2: SA and SB, after `python -m src.cell.characterize hd inv_1` has run
@pytest.mark.skipif(not (ROOT / "build/char/inv_1/sky130_fd_sc_hd__inv_1_sasb.json").exists(),
                    reason="run the inv_1 characterization first")
def test_inv1_stress_distances():
    data = json.loads((ROOT / "build/char/inv_1/sky130_fd_sc_hd__inv_1_sasb.json").read_text())
    for d in data["devices"]:
        assert d["sa"] == pytest.approx(0.26, abs=0.005) and d["sb"] == pytest.approx(0.26, abs=0.005)


# Table 5 broken case: tables indexed by the full ramp must fail the validation
@pytest.mark.skipif(not (ROOT / "results/char_validation_fullramp.txt").exists(),
                    reason="run the broken case first: python -m src.cell.char_validate --full-ramp")
def test_full_ramp_is_flagged():
    assert "TABLE 5 (delay, transition, capacitance, setup): FAIL" in (ROOT / "results/char_validation_fullramp.txt").read_text()
