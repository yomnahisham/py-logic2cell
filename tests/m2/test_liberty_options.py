"""Options of the Liberty and request writers for the final milestone: --names, --final-set,
--scale (the 30% experiment) and --out (the greedy selection's trial libraries)."""

import json
import re

import pytest

from src.hd import liberty_writer
from src.hd.cost import cost, expression
from src.hd.liberty_writer import groups, parse_scale
from src.hd.rank import cell_name, request_id
from src.hd.request_writer import final_set, selected
from src.hd.real_cells import RealCell
from src.paths import ROOT

LIBRARY = """library ("t") {
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


def candidate(table, n, area=11.2608, saving=1.0):
    c = cost(table, n)
    names = list("ABCD"[:n])
    return dict(rank=1, name=cell_name(table, n), request_id=request_id(table, n), inputs=names, output="Y",
                truth_table=f"0x{table:0{max(1, (1 << n) // 4)}X}", expression=expression(c, names),
                cost=dict(transistors=c.transistors), area_um2=area, saving_um2=dict(total=saving), buildable=True)


def areas(text):
    """Area of every new (dd2_) cell group in a Liberty text."""
    return dict(re.findall(r'cell \("(dd2_[^"]+)"\) \{\s*area : ([\d.]+);', text))


def test_parse_scale():
    assert parse_scale(["dd2_gc1__f077f_1=0.7", "x=1.5"]) == {"dd2_gc1__f077f_1": 0.7, "x": 1.5}
    assert parse_scale(None) == {}
    for bad in (["x"], ["x=abc"], ["=0.7"], ["x=0"], ["x=-1"]):
        with pytest.raises(SystemExit):
            parse_scale(bad)


def test_scale_changes_only_the_named_cell():
    maj4n, nand2 = candidate(0x077F, 4), candidate(0x7, 2, area=3.7536)
    text = groups([maj4n, nand2], LIBRARY, {maj4n["name"]: 0.7})
    assert areas(text) == {maj4n["name"]: "7.8826", nand2["name"]: "3.7536"}     # 11.2608 x 0.7, unchanged


def test_scale_of_a_cell_not_in_the_library_is_refused():
    with pytest.raises(SystemExit):
        groups([candidate(0x077F, 4)], LIBRARY, {"dd2_gc1__nothere_1": 0.7})


def test_final_set_file(tmp_path):
    path = tmp_path / "final_set.json"
    path.write_text(json.dumps({"cells": ["b", "a"]}))
    assert final_set(path) == ["b", "a"]
    path.write_text(json.dumps(["b", "a"]))
    with pytest.raises(SystemExit):
        final_set(path)
    with pytest.raises(SystemExit):
        final_set(tmp_path / "missing.json")


def test_named_cells_keep_the_given_order(tmp_path):
    ranked = tmp_path / "ranked.json"
    ranked.write_text(json.dumps(dict(candidates=[dict(name=n, saving_um2=dict(total=1)) for n in "abc"])))
    assert [c["name"] for c in selected(names=["c", "a"], ranked=ranked)] == ["c", "a"]
    with pytest.raises(SystemExit):
        selected(names=["a", "z"], ranked=ranked)


def test_names_and_final_set_together_are_refused():
    with pytest.raises(SystemExit):
        liberty_writer.main(["--names", "a", "--final-set"])


def test_real_mode_drops_failed_cells(tmp_path, monkeypatch):
    accepted, failed = candidate(0x077F, 4), candidate(0x007F, 4)
    real = groups([accepted], LIBRARY).replace(f"area : {accepted['area_um2']};",
                                                "area : 8.7584;", 1)

    def fake_intake(cand):
        return RealCell(cand["name"], real if cand is accepted else None,
                        "accepted" if cand is accepted else "status fail", None, None)

    monkeypatch.setattr(liberty_writer, "selected", lambda *args: [accepted, failed])
    monkeypatch.setattr("src.hd.real_cells.intake", fake_intake)
    out = tmp_path / "real.lib"
    liberty_writer.main(["--real", "--out", str(out)])

    text = out.read_text()
    assert f'cell ("{accepted["name"]}")' in text
    assert f'cell ("{failed["name"]}")' not in text


@pytest.mark.skipif(not (ROOT / "given").exists() or not (ROOT / "results/hd/ranked.json").exists(),
                    reason="needs make setup and results/hd/ranked.json")
def test_out_writes_only_that_library(tmp_path):
    top = selected(2)
    new_cells = ROOT / "libs/new_cells.lib"
    before = new_cells.read_text() if new_cells.exists() else None
    out = tmp_path / "trial.lib"
    liberty_writer.main(["--names", *(c["name"] for c in top), "--scale", f"{top[0]['name']}=0.7",
                         "--out", str(out)])
    written = areas(out.read_text())
    assert set(written) == {c["name"] for c in top}
    assert float(written[top[0]["name"]]) == pytest.approx(top[0]["area_um2"] * 0.7, abs=1e-4)
    assert float(written[top[1]["name"]]) == top[1]["area_um2"]
    assert (new_cells.read_text() if new_cells.exists() else None) == before
