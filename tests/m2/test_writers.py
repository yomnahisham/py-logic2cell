"""Request writer, Liberty writer, and the ranking rules of Table 3 and the saving."""

import json

import pytest

from src.common.request import RequestError
from src.common.request import truth_table as request_truth_table
from src.hd.cost import cost, expression
from src.hd.liberty import parse_liberty
from src.hd.liberty_writer import cell_group, depths, extend, reference, timing_sense
from src.hd.rank import cell_name, choose_polarity, decide, request_id, stat
from src.hd.cut_classes import Occurrences, pn_class
from src.hd.request_writer import request, selected

INV = """library ("t") {
  lu_table_template ("del") { variable_1 : "input_net_transition"; variable_2 : "total_output_net_capacitance";
    index_1("1, 2"); index_2("1, 2"); }
  cell ("sky130_fd_sc_hd__inv_1") {
    pin ("A") { direction : "input"; capacitance : 0.002; }
    pin ("Y") { direction : "output"; function : "(!A)";
      timing () { related_pin : "A";
        cell_fall ("del") { index_1("0.01, 0.1"); index_2("0.001, 0.01"); values("1, 2", "3, 4"); }
        cell_rise ("del") { index_1("0.01, 0.1"); index_2("0.001, 0.01"); values("5, 6", "7, 8"); }
        fall_transition ("del") { index_1("0.01, 0.1"); index_2("0.001, 0.01"); values("1, 1", "1, 0.5"); }
        rise_transition ("del") { index_1("0.01, 0.1"); index_2("0.001, 0.01"); values("1, 1", "1, 0.25"); } } }
  }
}
"""


def candidate(table, n):
    c = cost(table, n)
    names = list("ABCD"[:n])
    return dict(rank=1, name=cell_name(table, n), request_id=request_id(table, n), inputs=names, output="Y",
                truth_table=f"0x{table:0{max(1, (1 << n) // 4)}X}", expression=expression(c, names),
                cost=dict(transistors=c.transistors), area_um2=11.2608, saving_um2=dict(total=1.0))


def test_reference_reads_the_nearest_table_point():
    ref = reference(INV)
    assert ref == dict(capacitance=0.002, cell_rise=8, cell_fall=4, rise_transition=0.25, fall_transition=0.5)


def test_names_follow_the_truth_table():
    assert cell_name(0x077F, 4) == "dd2_gc1__f077f_1" and request_id(0x077F, 4) == "GC1-077F"
    assert cell_name(0x2B, 3) == "dd2_gc1__f2b_1"


def test_request_round_trips_through_option1_reader():
    data = request(candidate(0x077F, 4))
    assert data["expression"] == "!((C & D) | (A & B & (C | D)))" and data["sizing"] == "hd"
    bad = candidate(0x077F, 4) | {"truth_table": "0x077E"}
    with pytest.raises(RequestError):
        request(bad)


def test_liberty_cell_parses_back_to_its_truth_table():
    for table, n in ((0x077F, 4), (0x2B, 3), (0x6, 2)):
        group = cell_group(candidate(table, n), reference(INV))
        cell, = parse_liberty('library ("x") {\n' + group + "}\n")
        # cell.truth_table orders inputs as they first appear in the function: use pin order
        assert request_truth_table(cell.function, cell.inputs) == table and cell.area == 11.2608
        assert group.count("timing ()") == n


def test_timing_sense_and_depths():
    assert timing_sense(0x077F, 0) == "negative_unate"
    assert timing_sense(0x8888, 0) == "positive_unate"            # and2
    assert timing_sense(0x6666, 0) == "non_unate"                 # xor2
    c = cost(0x8, 2)                                              # and2: nand2 then an inverter
    assert depths(c, 0) == dict(cell_rise=3, cell_fall=2, rise_transition=1, fall_transition=1)


def test_extend_puts_cells_inside_the_library():
    assert extend('library ("x") {\n  a;\n}\n', "  cell;\n") == 'library ("x") {\n  a;\n  cell;\n}\n'


def test_selected_takes_positive_savings_in_rank_order(tmp_path):
    ranked = tmp_path / "ranked.json"
    ranked.write_text(json.dumps(dict(candidates=[
        dict(name="a", saving_um2=dict(total=5)), dict(name="b", saving_um2=dict(total=2)),
        dict(name="c", saving_um2=dict(total=-1))])))
    assert [c["name"] for c in selected(10, ranked=ranked)] == ["a", "b"]
    assert [c["name"] for c in selected(1, ranked=ranked)] == ["a"]
    assert [c["name"] for c in selected(10, ["c"], ranked=ranked)] == ["c"]


def test_table3_what_to_do():
    assert decide("exists", 1.0, 5.0, 3.0)[0] == "drop"
    assert decide("exists_inv", 7.0, 5.0, 3.0)[0] == "keep"       # 7 < 5 + 3
    assert decide("exists_inv", 8.0, 5.0, 3.0)[0] == "drop"
    assert decide("contained", 4.0, 5.0, 3.0)[0] == "keep"
    assert decide("contained", 5.0, 5.0, 3.0)[0] == "drop"
    assert decide("contained", None, 5.0, 3.0)[0] == "drop"
    assert decide("new", 9.0, None, 3.0)[0] == "keep"


def test_cheaper_polarity_is_chosen():
    occ = Occurrences()
    occ.add(1, 1, 0x8)                                            # seen as and2 only
    table, c = choose_polarity(2, pn_class(0x8, 2), [occ])
    assert (table, c.transistors) == (0x7, 4)                     # nand2 is built


def test_stat_reads_area_and_cells(tmp_path):
    log = tmp_path / "s.log"
    log.write_text("   Number of cells:        3\n     sky130_fd_sc_hd__dfxtp_1      2\n"
                   "     sky130_fd_sc_hd__nand2_1      1\n\n   Chip area for module '\\top': 45.7\n")
    assert stat(log) == (45.7, {"sky130_fd_sc_hd__dfxtp_1": 2, "sky130_fd_sc_hd__nand2_1": 1})
