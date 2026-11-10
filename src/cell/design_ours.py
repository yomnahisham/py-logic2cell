"""A small design mapped onto HD plus our generated cells, and timed with OpenSTA (option 1 handout, section 4
step 9): Tutorial 4's SPM.

    python -m src.cell.design_ours <Tutorial 4 folder with SPM.v, CSADD.v, TCMP.v, synth.ys, abc_constr.txt>

The library is build/sta/hd_plus_ours.lib: the HD Liberty with every cells/<name>/cell.lib cell group added
(the files `liberty_write cell` wrote, as they are). The HD cells stay, so ABC is free to choose ours or
HD's; which of ours it took, and how often, is counted from the netlist. Mapping and timing are those of
src.cell.spm_design (Tutorial 4's synth.ys settings), so the `hd` run is the same baseline as Table 5's.
Writes results/design_ours.txt; netlists and logs in build/spm/hd/ and build/spm/hd_plus_ours/.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

from src.cell.liberty_timing import cell_text
from src.cell.spm_design import copy_sources, synthesize, time_it, tutorial_settings, yosys_version
from src.cell.tools import STA_IMAGE
from src.paths import LIBERTY_TT

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "build/sta/hd_plus_ours.lib"
STAMP = re.compile(r"^/\* Characterized by .*?sha256 ([0-9a-f]{64}).*?\*/\n")


def merged_library() -> tuple[Path, list[str], str]:
    """HD with our cell groups added before the library's closing brace; returns (path, our cells, sha)."""
    libs = sorted((ROOT / "cells").glob("*/cell.lib"))
    if not libs:
        raise FileNotFoundError("no cells/*/cell.lib: run python -m src.cell.liberty_write cell <requests> first")
    groups, names, shas = [], [], set()
    for lib in libs:
        text = lib.read_text()
        m = STAMP.match(text)
        if not m:
            raise ValueError(f"{lib}: no ngspice stamp on the first line")
        shas.add(m[1])
        name = lib.parent.name
        groups.append("    " + cell_text(lib, name).strip() + "\n")
        names.append(name)
    if len(shas) != 1:                                 # one library never mixes two ngspice builds
        raise ValueError(f"cells/*/cell.lib come from more than one ngspice build: {sorted(shas)}")
    hd = LIBERTY_TT.read_text()
    for n in names:
        if f'cell ("{n}")' in hd:
            raise ValueError(f"{n} is already in {LIBERTY_TT.name}")
    end = hd.rstrip().rindex("}")                     # the library group's closing brace
    sha = shas.pop()
    # no "*/" inside the comment: a path like cells/*/cell.lib would end it early
    head = (f"/* {LIBERTY_TT.name} with {len(names)} generated cells added (cells/<name>/cell.lib); those were "
            f"characterized with ngspice sha256 {sha} */\n")
    LIB.parent.mkdir(parents=True, exist_ok=True)
    LIB.write_text(head + hd[:end] + "".join(groups) + hd[end:])
    return LIB, names, sha


def used(netlist: Path) -> Counter:
    return Counter(re.findall(r"^\s*(dd2_gc1__\w+)\s", netlist.read_text(), re.M))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    tut = copy_sources(Path(sys.argv[1]).expanduser().resolve())
    lib, ours, sha = merged_library()
    settings = tutorial_settings(tut)
    version = yosys_version()
    hd_net = synthesize(tut, LIBERTY_TT, "hd", settings)
    mix_net = synthesize(tut, lib, "hd_plus_ours", settings)
    hd, mix = time_it(hd_net, LIBERTY_TT, "hd", settings), time_it(mix_net, lib, "hd_plus_ours", settings)
    counts = used(mix_net)
    total = hd["cells"]
    lines = [f"SPM mapped onto HD plus our generated cells (section 4 step 9): {version}; OpenSTA in {STA_IMAGE}",
             f"settings from {sys.argv[1]}: ABC -D {settings['period_ps']} ps (also the clock period), driving cell "
             f"{settings['driving_cell']}, output load {settings['load_ff']} fF",
             f"library {lib.relative_to(ROOT)}: {LIBERTY_TT.name} plus {len(ours)} cells from cells/*/cell.lib, "
             f"ngspice sha256 {sha}", ""]
    for r, n in ((hd, hd["cells"]), (mix, mix["cells"] + sum(counts.values()))):
        lines.append(f"{r['tag']:13s} worst path {r['arrival_ns']:.4f} ns, worst slack {r['slack_ns']:+.4f} ns, "
                     f"{n} cells, area {r['area']} um2, {r['start']} -> {r['end']}")
    d = mix["arrival_ns"] - hd["arrival_ns"]
    lines += ["", f"change in worst delay: {d * 1000:+.1f} ps ({d / hd['arrival_ns'] * 100:+.2f}%); "
              f"area {float(mix['area']) - float(hd['area']):+.3f} um2", "",
              f"our cells chosen by ABC: {sum(counts.values())} instances of {len(counts)} cells"]
    lines += [f"  {c:26s} {k}" for c, k in counts.most_common()]
    lines += [f"  not used: {', '.join(sorted(set(ours) - set(counts)))}", "",
              f"design mapped with at least one generated cell and timed: {'PASS' if counts else 'FAIL'}"]
    (ROOT / "results/design_ours.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    sys.exit(0 if counts else 1)
