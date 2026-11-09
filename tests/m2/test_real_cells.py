"""Real cells from Option 1 (src/hd/real_cells.py) and their use in the Liberty file, with the broken
cases in tests/broken/m2_real_cells/ that the intake must refuse."""

import json
import re

import pytest

from src.hd.cost import cost, expression
from src.hd.liberty_writer import groups
from src.hd.rank import cell_name, request_id
from src.hd.real_cells import check_group, intake
from src.paths import ROOT

BROKEN = ROOT / "tests/broken/m2_real_cells"
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


def candidate(table=0x077F, n=4):
    c = cost(table, n)
    names = list("ABCD"[:n])
    return dict(rank=1, name=cell_name(table, n), request_id=request_id(table, n), inputs=names, output="Y",
                truth_table=f"0x{table:0{max(1, (1 << n) // 4)}X}", expression=expression(c, names),
                cost=dict(transistors=c.transistors), area_um2=11.2608, saving_um2=dict(total=1.0), buildable=True)


def returned(tmp_path, cand, group, status="pass"):
    """A folder like cells/ holding the maker's answer for one cell."""
    folder = tmp_path / cand["name"]
    folder.mkdir(parents=True)
    (folder / "cell.lib").write_text(group)
    (folder / "response.json").write_text(json.dumps(dict(
        request_id=cand["request_id"], status=status, reason=None, cell=cand["name"], transistors=12,
        width_sites=7, area_um2=8.7584, files=dict(liberty=str(folder / "cell.lib")))))
    return tmp_path


def real_group(cand, area=8.7584):
    """A returned cell group: our estimated group with the maker's area, standing in for a real one."""
    estimated = groups([cand], LIBRARY)
    return re.sub(r"area : [\d.]+;", f"area : {area};", estimated, count=1)


def test_a_good_cell_is_accepted_and_replaces_the_estimate(tmp_path):
    cand = candidate()
    r = intake(cand, returned(tmp_path, cand, real_group(cand)))
    assert r.reason == "accepted" and r.area_um2 == 8.7584
    text = groups([cand], LIBRARY, real={cand["name"]: r.group})
    assert "area : 8.7584;" in text and "area : 11.2608;" not in text


def test_scale_applies_to_a_real_cell(tmp_path):
    cand = candidate()
    r = intake(cand, returned(tmp_path, cand, real_group(cand)))
    text = groups([cand], LIBRARY, scale={cand["name"]: 0.7}, real={cand["name"]: r.group})
    assert "area : 6.1309;" in text                                   # 8.7584 x 0.7


def test_broken_wrong_function_is_refused():
    r = intake(candidate(), BROKEN / "wrong_function")
    assert r.group is None and "gives 0x" in r.reason


def test_broken_status_fail_is_refused():
    r = intake(candidate(), BROKEN / "not_pass")
    assert r.group is None and r.reason.startswith("status fail")


def test_missing_response_or_liberty_keeps_the_estimate(tmp_path):
    cand = candidate()
    assert intake(cand, tmp_path).reason == "no response yet"
    folder = tmp_path / cand["name"]
    folder.mkdir()
    (folder / "response.json").write_text(json.dumps(dict(status="pass", cell=cand["name"], files={})))
    assert "files.liberty" in intake(cand, tmp_path).reason


@pytest.mark.parametrize("change, message", [
    (lambda g: g.replace('pin ("D")', 'pin ("E")'), "pins"),
    (lambda g: g.replace("dd2_gc1__f077f_1", "dd2_gc1__other_1"), "cell group is"),
    (lambda g: g + g, "2 cell groups"),
    (lambda g: re.sub(r"area : [\d.]+;", "", g), "area"),
    (lambda g: re.sub(r'timing \(\) \{\s*related_pin : "D";.*?\n      \}\n', "", g, flags=re.S), "timing"),
])
def test_each_rule_of_appendix_a_is_checked(change, message):
    cand = candidate()
    with pytest.raises(ValueError, match=message):
        check_group(cand, change(real_group(cand)))
