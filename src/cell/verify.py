"""DRC (in a row with tap cells), extraction, LVS and RC-LVS for one generated cell.

    python -m src.cell.verify build/cells/<name>        (needs <name>.gds and <name>.spice)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import klayout.db as kdb

from src.cell.tools import LVS_SETUP, TECH, run
from src.paths import GDS as HD_GDS, PREFIX

MAGIC = ["-dnull", "-noconsole", "-rcfile", "/dev/null"]
MAGIC_ERRORS = r"(invalid command|Error|Unknown option|cannot|Could not)"


def with_taps(folder: Path, name: str) -> str:
    """tap | cell | tap, flattened, so nwell.4 and the latch-up rules can pass."""
    layout = kdb.Layout()
    layout.read(str(HD_GDS))
    tap = layout.cell(PREFIX + "tapvpwrvgnd_1")
    cell_layout = kdb.Layout()
    cell_layout.read(str(folder / f"{name}.gds"))
    cell = layout.create_cell(name)
    cell.copy_tree(cell_layout.top_cell())
    width = json.loads((folder / f"{name}.json").read_text())["width"]
    row = layout.create_cell(f"{name}_row")
    row.insert(kdb.DCellInstArray(tap.cell_index(), kdb.DTrans(0, 0)))
    row.insert(kdb.DCellInstArray(cell.cell_index(), kdb.DTrans(0.46, 0)))
    row.insert(kdb.DCellInstArray(tap.cell_index(), kdb.DTrans(0.46 + width, 0)))
    row.flatten(True)
    for info in [(67, 5), (68, 5), (64, 5), (64, 59)]:
        index = layout.find_layer(*info)
        if index is not None:
            row.shapes(index).clear()
    options = kdb.SaveLayoutOptions()
    options.select_cell(row.cell_index())
    layout.write(str(folder / f"{name}_row.gds"), options)
    return row.name


def magic_drc(folder: Path, top: str) -> tuple[int, str]:
    script = f"""tech load {TECH}
gds read {top}.gds
load {top}
select top cell
drc style drc(full)
drc check
drc catchup
puts "DRC_COUNT [drc list count total]"
puts "DRC_WHY [drc listall why]"
quit -noprompt
"""
    out = run("magic", MAGIC, folder, folder / f"{top}_drc.log", stdin=script)
    count = re.search(r"DRC_COUNT (\d+)", out)
    if not count:
        raise RuntimeError(f"Magic stopped early, see {folder / f'{top}_drc.log'}")
    why = re.search(r"DRC_WHY (.*)", out)
    return int(count[1]), why[1] if why else ""


def magic_extract(folder: Path, name: str, ports: list[str]):
    lines = [f"tech load {TECH}", f"gds read {name}.gds", f"load {name}", "select top cell"]
    lines += [f"port {pin} make {i}" for i, pin in enumerate(ports, 1)]
    lines += ["extract all", "ext2spice lvs", f"ext2spice -o {name}_lvs.spice",
              "ext2spice cthresh 0", f"ext2spice -o {name}_cap.spice",
              "extresist threshold 0", "extresist minres 1", "extresist mindelay 0",
              "extract do resistance", "extract all", "ext2spice extresist on",
              f"ext2spice -o {name}_pex.spice", 'puts "MAGIC_DONE"', "quit -noprompt"]
    out = run("magic", MAGIC, folder, folder / f"{name}_extract.log", stdin="\n".join(lines) + "\n")
    if "MAGIC_DONE" not in out or re.search(MAGIC_ERRORS, out):
        raise RuntimeError(f"Magic did not extract cleanly, see {folder / f'{name}_extract.log'}")


def lvs(folder: Path, layout_net: str, layout_cell: str, schematic: str, schematic_cell: str) -> bool:
    report = folder / f"{layout_net}_vs_{Path(schematic).stem}.log"
    run("netgen", ["-batch", "lvs", f"{layout_net}.spice {layout_cell}", f"{schematic} {schematic_cell}",
                   str(LVS_SETUP), str(report)], folder, folder / f"{layout_net}_netgen.log")
    text = report.read_text().lower()
    return "circuits match uniquely." in text and "do not match" not in text and "property errors" not in text


def collapse_rc(folder: Path, name: str) -> tuple[int, int]:
    """Merge the nodes every extracted resistor joins; LVS on the result finds shorts and opens."""
    source = (folder / f"{name}_pex.spice").read_text()
    parent = {}

    def find(n):
        parent.setdefault(n, n)
        if parent[n] != n:
            parent[n] = find(parent[n])
        return parent[n]

    ports = re.search(r"(?im)^\.subckt\s+\S+\s+(.+)", source)[1].split()
    r = c = 0
    for line in source.splitlines():
        if re.match(r"^R\S*\s", line):
            _, a, b, *_ = line.split()
            parent[find(b)] = find(a)
            r += 1
        elif re.match(r"^C\S*\s", line):
            c += 1
    if len({find(p) for p in ports}) != len(ports):
        raise RuntimeError(f"the extracted wiring of {name} shorts two ports")
    by_root = {find(p): p for p in ports}
    lines = [f".subckt {name} {' '.join(ports)}"]
    for line in source.splitlines():
        if line.startswith("X"):
            tok = line.split()
            tok[1:5] = [by_root.get(find(n), find(n)) for n in tok[1:5]]
            lines.append(" ".join(tok))
    (folder / f"{name}_rc.spice").write_text("\n".join(lines + [".ends", ""]))
    return r, c


def verify(folder: Path, name: str) -> dict:
    meta = json.loads((folder / f"{name}.json").read_text())
    ports = meta["inputs"] + ["VGND", "VNB", "VPB", "VPWR", meta["output"]]
    result = {}
    result["drc"], result["drc_why"] = magic_drc(folder, with_taps(folder, name))
    magic_extract(folder, name, ports)
    result["lvs"] = "match" if lvs(folder, f"{name}_lvs", name, f"{name}.spice", name) else "fail"
    result["rc_r"], result["rc_c"] = collapse_rc(folder, name)
    result["rc_lvs"] = "match" if lvs(folder, f"{name}_rc", name, f"{name}.spice", name) else "fail"
    (folder / f"{name}_verify.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    folder = Path(sys.argv[1]).resolve()
    result = verify(folder.parent, folder.name)
    print(json.dumps({k: v for k, v in result.items() if k != "drc_why" or v}, indent=2))
    sys.exit(0 if result["drc"] == 0 and result["lvs"] == result["rc_lvs"] == "match" else 1)
