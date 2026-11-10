"""The gate-level simulation script: models, verdicts and the broken cases' logic, without Yosys or the PDK.
The full flow (make gls) is the test of the cells themselves; these keep the checks' own logic honest."""

import shutil
import subprocess

import pytest

from src.hd import gls

F17 = {"name": "dd2_gc1__f17_1", "inputs": ["A", "B", "C"], "output": "Y", "truth_table": "0x17"}
F2B = {"name": "dd2_gc1__f2b_1", "inputs": ["A", "B", "C"], "output": "Y", "truth_table": "0x2B"}   # not symmetric


def test_verdict_needs_exit_zero_and_a_pass_line():
    assert gls.verdict(0, "  ok: 1 x 2 = 2\nPASS: all 65536 signed input pairs correct\n")
    assert not gls.verdict(1, "PASS: all correct\n")                       # $fatal gives exit status 1
    assert not gls.verdict(0, "ok\n")                                      # no PASS line at all
    assert not gls.verdict(0, "PASS: x\nERROR: mp=1 mc=2 expected=2 got=3\n")
    assert not gls.verdict(0, "MISMATCH: mp=1\nPASS: x\n")


def test_a_compile_error_is_never_a_caught_broken_case():
    assert gls.functional_fail(False, "FAIL: 13312/65536 mismatches")
    assert not gls.functional_fail(False, "compile error: Unknown module type")
    assert not gls.functional_fail(True, "PASS: ok")


def test_swap_changes_one_instance_to_a_cell_with_the_same_pins():
    netlist = "  sky130_fd_sc_hd__xor2_1 _1_ (\n .A(a), .B(b), .X(x));\n  sky130_fd_sc_hd__xor2_1 _2_ (\n"
    bad, what = gls.swap_cell(netlist)
    assert bad.count("sky130_fd_sc_hd__xor2_1") == 1 and bad.count("sky130_fd_sc_hd__or2_1") == 1
    assert "xor2_1" in what
    assert gls.swap_cell("  sky130_fd_sc_hd__inv_1 _1_ (\n") is None


def test_new_cell_counts_only_counts_instances():
    text = "  dd2_gc1__f17_1 _3_ (\n .A(a));\n  dd2_gc1__f17_1 _4_ (\n  sky130_fd_sc_hd__inv_1 _5_ (\n"
    assert gls.new_cell_counts(text) == {"dd2_gc1__f17_1": 2}


def test_model_text_has_the_cells_ports_and_width():
    m = gls.truth_table_model(F17)
    assert "module dd2_gc1__f17_1 (A, B, C, Y);" in m and "8'h17" in m and "TT[{C, B, A}]" in m
    assert "8'hE8" in gls.truth_table_model(F17, invert=True)              # 0x17 ^ 0xFF
    with pytest.raises(ValueError):
        gls.truth_table_model({**F17, "truth_table": "0x1FF"})            # does not fit 3 inputs


def test_corrupt_function_complements_it_and_back():
    lib = 'cell ("a") { pin ("Y") { function : "!(A&B)"; } }\ncell ("b") { pin ("Y") { function : "A|B"; } }\n'
    once = gls.corrupt_function(lib, "a")
    assert 'function : "(A&B)"' in once                                    # "!(A&B)" lost its inversion
    assert 'function : "A|B"' in once                                       # the other cell is untouched
    assert gls.corrupt_function(lib, "b").count('function : "!(A|B)"') == 1


@pytest.mark.skipif(shutil.which("iverilog") is None, reason="needs Icarus Verilog")
def test_model_follows_the_request_bit_order(tmp_path):
    """Bit i of the table is Y for the input combination whose input k is bit k of i: A is the least significant.
    0x2B is used because 0x17 (an inverted majority) is symmetric and would pass with any input order."""
    tb = tmp_path / "tb.v"
    tb.write_text("""module tb; reg a,b,c; wire y; integer i, bad; dd2_gc1__f2b_1 u(.A(a),.B(b),.C(c),.Y(y));
      initial begin bad = 0; for (i = 0; i < 8; i = i + 1) begin {c,b,a} = i; #1;
        if (y !== ((8'h2B >> i) & 1)) bad = bad + 1; end
        if (bad == 0) $display("PASS"); else $display("FAIL"); end endmodule""")
    (tmp_path / "m.v").write_text(gls.truth_table_model(F2B))
    subprocess.run(["iverilog", "-o", str(tmp_path / "t"), str(tb), str(tmp_path / "m.v")], check=True)
    assert "PASS" in subprocess.run(["vvp", str(tmp_path / "t")], text=True, stdout=subprocess.PIPE).stdout