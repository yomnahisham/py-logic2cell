"""The area model (src/hd/area_model.py), on the PDK's own files. Needs make setup."""

import pytest

from src.hd.area_model import Model, errors, fit, lef_widths, site, spice_transistors, training_rows
from src.paths import ROOT, SPICE

pytestmark = pytest.mark.skipif(not SPICE.exists() or not (ROOT / "given").exists(), reason="needs make setup")


def test_pdk_facts_are_read_not_typed():
    assert site() == (0.46, 2.72)
    assert spice_transistors()["sky130_fd_sc_hd__nand2_1"] == 4
    assert spice_transistors()["sky130_fd_sc_hd__a21o_1"] == 8
    assert lef_widths()["sky130_fd_sc_hd__nand2_1"] == 1.38


def test_training_set_is_x1_combinational():
    rows = training_rows()
    assert rows and all(r["cell"].endswith("_1") for r in rows)
    assert {"nand2_1", "a21o_1", "mux2_1"} <= {r["cell"] for r in rows}
    assert not any(r["cell"].startswith(("dfxtp", "dlygate", "clkbuf", "fa_", "ha_")) for r in rows)


def test_model_grows_with_transistors_and_rounds_up():
    model = fit()
    assert model.b > 0
    assert model.sites(12) >= model.a + model.b * 12
    assert model.area(12) == pytest.approx(model.sites(12) * 0.46 * 2.72)


def test_errors_are_reported_per_group():
    rows = [dict(transistors=4, sites=3, stages="single"), dict(transistors=8, sites=6, stages="multi")]
    e = errors(Model(0.0, 0.75, 0.46, 2.72), rows)
    assert (e["single"]["cells"], e["multi"]["cells"], e["all"]["cells"]) == (1, 1, 2)
    assert e["single"]["max_abs_sites"] == 0 and e["multi"]["max_abs_sites"] == 0
