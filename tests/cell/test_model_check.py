"""Model-level check (option 1 handout, section 4.2 level 3) and the round trip of section 3.3, on the
delivered nand2_1, with the broken cases: a Verilog model and a Liberty function with one wrong row."""

import re
from pathlib import Path

import pytest

from src.cell.model_check import model_check

ROOT = Path(__file__).resolve().parents[2]
REQUEST = ROOT / "requests/hd/nand2_1.json"
CELL = ROOT / "cells/dd2_gc1__nand2_1"

pytestmark = pytest.mark.skipif(not (CELL / "cell.lib").exists(), reason="run python -m src.cell.deliver first")


def test_model_and_round_trip_pass():
    r = model_check(REQUEST)
    assert r["model"] == "pass"
    assert r["round_trip"]["pass"], r["round_trip"]


def test_broken_verilog_one_wrong_row(tmp_path):
    # Y flipped for A=0, B=0 only: every other row stays right
    text = (CELL / "cell.v").read_text()
    broken = tmp_path / "cell.v"
    broken.write_text(re.sub(r"assign Y = (.*);", r"assign Y = (\1) ^ (~A & ~B);", text))
    r = model_check(REQUEST, verilog=broken, trip=False)
    assert r["verilog"]["table"] == "0x6"
    assert r["model"] == "fail"


def test_broken_liberty_one_wrong_row():
    lib = (CELL / "cell.lib").read_text().replace('function : "!(A & B)"', 'function : "!(A & B) ^ (!A & !B)"')
    r = model_check(REQUEST, lib=lib, trip=False)
    assert r["liberty"]["table"] == "0x6"
    assert r["model"] == "fail"


def test_broken_liberty_fails_round_trip():
    # a cell whose Liberty function is not the request's: no script can use it for the requested design,
    # so the round trip fails (cec alone would not: the mapper only uses a cell for the function it claims)
    lib = (CELL / "cell.lib").read_text().replace('function : "!(A & B)"', 'function : "!(A | B)"')
    r = model_check(REQUEST, lib=lib)
    assert [r["round_trip"][k]["our_cell_instances"] for k in ("free_A", "free_B", "forced_A", "forced_B")] == [0, 0, 0, 0]
    assert r["round_trip"]["pass"] is False
