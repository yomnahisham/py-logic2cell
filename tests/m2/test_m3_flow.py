"""Pieces of the final milestone's flow that run without the tools: the OpenSTA set-up and report
parsing (src/hd/sta.py), the 30% experiment's instance count (src/hd/sensitivity.py), the
per-design comparison (src/hd/analysis.py) and the demo's design path rule (src/hd/demo.py)."""

from pathlib import Path

import pytest

from src.hd import demo
from src.hd.analysis import overlap_text
from src.hd.sensitivity import instances
from src.hd.sta import clocks, script, worst

NETLIST = """module top(clk, rst, a, y);
  input clk;
  input rst;
  input [3:0] a;
  output y;
  sky130_fd_sc_hd__dfrtp_1 _1_ (
    .CLK(clk),
    .D(_0_),
    .Q(y),
    .RESET_B(rst)
  );
  sky130_fd_sc_hd__nand2_1 _2_ (
    .A(a[0]),
    .B(a[1]),
    .Y(_0_)
  );
endmodule
"""

REPORT = """Startpoint: rst (input port clocked by clk)
Endpoint: _1_ (recovery check against rising-edge clock clk)
   0.1200   data arrival time
Startpoint: a[0] (input port clocked by clk)
Endpoint: _1_ (rising edge-triggered flip-flop clocked by clk)
   0.3456   data arrival time
"""


def test_clocks_are_inputs_driving_a_clock_pin():
    sequential = {"sky130_fd_sc_hd__dfrtp_1"}
    assert clocks(NETLIST, sequential) == ["clk"]
    assert clocks(NETLIST, set()) == []                     # no sequential cell, no clock


def test_sta_script_constrains_every_path():
    text = script(Path("n.v"), Path("l.lib"), "top", ["clk"])
    assert "create_clock -name clk" in text and "set_input_delay 0 -clock clk" in text
    assert "set_output_delay 0 -clock clk [all_outputs]" in text
    assert "-unconstrained" in script(Path("n.v"), Path("l.lib"), "top", [])


def test_worst_takes_the_largest_arrival():
    assert worst(REPORT) == dict(worst_delay_ns=0.3456, startpoint="a[0]", endpoint="_1_")
    with pytest.raises(RuntimeError):
        worst("No paths found.")


def test_instances_counts_one_cell():
    log = ("   Number of cells: 3\n     dd2_gc1__f077f_1      2\n     dd2_gc1__f077f_10      5\n"
           "     sky130_fd_sc_hd__nand2_1      1\n")
    assert instances(log, "dd2_gc1__f077f_1") == 2
    assert instances(log, "dd2_gc1__other_1") == 0


def test_overlap_text_names_shared_cells_and_missing_designs():
    best = {"risc8": [dict(cell="x"), dict(cell="y")], "pic16": [dict(cell="y"), dict(cell="z")]}
    text = "\n".join(overlap_text(best))
    assert "no cuts or baseline log yet for p16c5x" in text
    assert "risc8 and pic16: 1 of their best 2 cells shared: y" in text


def test_demo_needs_the_path_argument_for_a_design_outside_given(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(demo.aigs, "write", lambda design, top: calls.append(design) or {})
    monkeypatch.setattr(demo.aigs, "OUT", tmp_path / "aigs")
    other = tmp_path / "mine.v"
    with pytest.raises(SystemExit, match="no path argument"):
        demo.aig("mine", "top", other)
    assert calls == []
