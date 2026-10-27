"""Layout checks on generated cells, and the broken case each must fail on. Needs docker."""

import json
import re
import shutil
from pathlib import Path

import klayout.db as kdb
import pytest

from src.cell import abutment, layout, simulate, verify
from src.cell.network import build_stage, euler_order, schematic
from src.layer_check import check as layer_check

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "build/tests"


def generate(name, inputs, expression, monkeypatch=None, **overrides):
    folder = WORK / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    for key, value in overrides.items():
        monkeypatch.setattr(layout, key, value)
    stage = build_stage(inputs, "Y", expression)
    component, meta = layout.draw(name, stage, euler_order(stage))
    meta.update(inputs=list(inputs), output="Y")
    component.write_gds(str(folder / f"{name}.gds"), with_metadata=False)
    (folder / f"{name}.spice").write_text(schematic(stage, name, 0.65, 1.0))
    (folder / f"{name}.json").write_text(json.dumps(meta))
    return folder


def edit_gds(path, layer, keep=None, cut=None):
    """Replace a layer's shapes with `keep`, or cut the box `cut` (um) out of it."""
    ly = kdb.Layout()
    ly.read(str(path))
    top = ly.top_cell()
    index = ly.layer(*layer)
    region = kdb.Region(top.shapes(index))
    if cut is not None:
        region -= kdb.Region(kdb.DBox(*cut).to_itype(ly.dbu))
    if keep is not None:
        region = kdb.Region(kdb.DBox(*keep).to_itype(ly.dbu))
    top.shapes(index).clear()
    top.shapes(index).insert(region)
    ly.write(str(path))


@pytest.fixture(scope="module")
def nand2():
    folder = generate("t_nand2", ("A", "B"), "!(A & B)")
    return folder, verify.verify(folder, "t_nand2")


def test_nand2_passes(nand2):
    folder, result = nand2
    assert result["drc"] == 0
    assert result["lvs"] == result["rc_lvs"] == "match"
    assert layer_check(str(folder / "t_nand2.gds"))
    assert simulate.simulate(folder, "t_nand2", 0x7)["passed"]
    assert abutment.check(folder, "t_nand2")["passed"]


def test_broken_drc_diffusion_overlap_of_contact(monkeypatch):
    folder = generate("t_drc", ("A", "B"), "!(A & B)", monkeypatch, CUT_DIFF=0.03)
    count, why = verify.magic_drc(folder, verify.with_taps(folder, "t_drc"))
    assert count > 0 and "licon.5a" in why


def test_broken_lvs_gap_in_output():
    folder = generate("t_lvs", ("A", "B"), "!(A & B)")
    edit_gds(folder / "t_lvs.gds", (67, 20), cut=(0, 1.38, 1.38, 1.385))   # 5 nm gap across the Y crossing
    result = verify.verify(folder, "t_lvs")
    assert result["lvs"] == "fail"


def test_broken_abutment_nwell_short_of_edge():
    folder = generate("t_abut", ("A", "B"), "!(A & B)")
    edit_gds(folder / "t_abut.gds", (64, 20), keep=(0.3, 1.305, 1.08, 2.91))
    assert not abutment.check(folder, "t_abut")["passed"]


def test_broken_simulation_missing_pullup(nand2):
    folder, _ = nand2
    broken = folder.parent / "t_sim"
    shutil.rmtree(broken, ignore_errors=True)
    broken.mkdir()
    pex = (folder / "t_nand2_pex.spice").read_text().replace("t_nand2", "t_sim")
    pfets = [line for line in pex.splitlines() if "pfet" in line and line.startswith("X")]
    pex = pex.replace(pfets[0] + "\n", "")
    (broken / "t_sim_pex.spice").write_text(pex)
    (broken / "t_sim.json").write_text((folder / "t_nand2.json").read_text())
    assert not simulate.simulate(broken, "t_sim", 0x7)["passed"]


def test_broken_layer_check_no_hvtp():
    folder = generate("t_hvtp", ("A",), "!A")
    edit_gds(folder / "t_hvtp.gds", (78, 44), keep=(0, 2.6, 1.38, 2.72))
    assert not layer_check(str(folder / "t_hvtp.gds"))
