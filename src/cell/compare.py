"""Compare a generated cell with the installed HD cell (option 1 handout, Table 4).

    python -m src.cell.compare build/cells/<name> <hd cell, e.g. nand2_1>
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import klayout.db as kdb

from src.cell.verify import lvs, magic_extract
from src.paths import GDS as HD_GDS, PREFIX, SPICE as HD_SPICE

PLAN = json.loads((Path(__file__).resolve().parents[2] / "given/plan_hd.json").read_text())["frame"]
FRAME_LAYERS = {"boundary": (236, 0), "nwell": (64, 20), "nsdm": (93, 44), "psdm": (94, 20), "hvtp": (78, 44)}
RAILS = (68, 20)
PIN_LAYERS = {(67, 16): "li1", (68, 16): "met1", (64, 16): "nwell", (122, 16): "pwell"}
LABEL_LAYERS = {(67, 5): "li1", (68, 5): "met1", (64, 5): "nwell", (64, 59): "pwell"}
WIRING = {(67, 20): "li1", (68, 20): "met1", (69, 20): "met2"}
TOL = 0.001


def load(path: Path, cell_name: str | None = None):
    layout = kdb.Layout()
    layout.read(str(path))
    cell = layout.cell(cell_name) if cell_name else layout.top_cell()
    return layout, cell


def region(layout, cell, layer):
    index = layout.find_layer(*layer)
    return kdb.Region(cell.begin_shapes_rec(index)) if index is not None else kdb.Region()


def boxes(layout, cell, layer):
    r = region(layout, cell, layer)
    return [b.to_dtype(layout.dbu) for b in (p.bbox() for p in r.each())]


def frame(layout, cell) -> dict:
    out = {}
    for key, layer in FRAME_LAYERS.items():
        bb = region(layout, cell, layer).bbox().to_dtype(layout.dbu)
        out[key] = [round(bb.bottom, 3), round(bb.top, 3)]
    rails = boxes(layout, cell, RAILS)
    out["VGND"] = next(([round(b.bottom, 3), round(b.top, 3)] for b in rails if b.bottom < 0), None)
    out["VPWR"] = next(([round(b.bottom, 3), round(b.top, 3)] for b in rails if b.top > 2.72), None)
    return out


def expected_frame() -> dict:
    return {"boundary": PLAN["boundary"]["y"], "nwell": PLAN["nwell"]["y"], "nsdm": PLAN["nsdm"]["y"],
            "psdm": PLAN["psdm"]["y"], "hvtp": PLAN["hvtp"]["y"],
            "VGND": PLAN["rails"]["VGND"]["met1"]["y"], "VPWR": PLAN["rails"]["VPWR"]["met1"]["y"]}


def xor(ours, theirs) -> dict:
    out = {}
    for key, layer in {**FRAME_LAYERS, "rails": RAILS}.items():
        a = region(*ours, layer)
        b = region(*theirs, layer)
        out[key] = round((a ^ b).area() * ours[0].dbu ** 2, 6)
    return out


def pins(layout, cell) -> dict:
    """Every pin label with the layer it is on, its y band and the size of the pin shape under it."""
    shapes = {name: boxes(layout, cell, layer) for layer, name in PIN_LAYERS.items()}
    out = defaultdict(list)
    for layer, name in LABEL_LAYERS.items():
        index = layout.find_layer(*layer)
        if index is None:
            continue
        for s in cell.shapes(index).each():
            if not s.is_text():
                continue
            x, y = s.text_pos.x * layout.dbu, s.text_pos.y * layout.dbu
            under = [b for b in shapes[name] if b.left - TOL <= x <= b.right + TOL and b.bottom - TOL <= y <= b.top + TOL]
            size = [round(under[0].width(), 3), round(under[0].height(), 3)] if under else None
            band = ("npc" if PLAN["npc_band"]["y"][0] <= y <= PLAN["npc_band"]["y"][1] else
                    "VGND rail" if abs(y) < 0.25 else "VPWR rail" if abs(y - 2.72) < 0.25 else "row")
            out[s.text_string].append(dict(layer=name, band=band, size=size))
    return dict(out)


def wiring(layout, cell) -> dict:
    """Wiring layers used, and whether met1 stays inside the rail bands."""
    used = [name for layer, name in WIRING.items() if not region(layout, cell, layer).is_empty()]
    met1 = region(layout, cell, RAILS)
    rails = kdb.Region()
    width = region(layout, cell, (236, 0)).bbox().width() or met1.bbox().width()
    for rail in ("VGND", "VPWR"):
        lo, hi = PLAN["rails"][rail]["met1"]["y"]
        rails.insert(kdb.DBox(-1, lo, width * layout.dbu + 1, hi).to_itype(layout.dbu))
    return {"layers": used, "met1_only_rails": (met1 - rails).is_empty()}


def gates(layout, cell) -> dict:
    """Gate x positions and pitch, diffusion strips per row, and gate order by nearest input label."""
    poly = region(layout, cell, (66, 20))
    diff = region(layout, cell, (65, 20))
    channels = (poly & diff)
    xs = sorted({round(b.center().x, 3) for b in (p.bbox().to_dtype(layout.dbu) for p in channels.each())})
    rows = defaultdict(int)
    for b in boxes(layout, cell, (65, 20)):
        rows["n" if b.top < 1.2 else "p"] += 1
    labels = []
    index = layout.find_layer(67, 5)
    for s in cell.shapes(index).each():
        if s.is_text() and PLAN["npc_band"]["y"][0] <= s.text_pos.y * layout.dbu <= PLAN["npc_band"]["y"][1]:
            labels.append((s.text_pos.x * layout.dbu, s.text_string))
    inputs = sorted({name for _, name in labels if name != "Y"})
    order = [min(((abs(x - lx), n) for lx, n in labels if n in inputs), default=(0, "?"))[1] for x in xs]
    pitch = sorted({round(b - a, 3) for a, b in zip(xs, xs[1:])})
    return {"gate_x": xs, "order": order, "pitch": pitch, "diffusion_breaks": {k: v - 1 for k, v in rows.items()}}


def parasitics(folder: Path, name: str) -> dict:
    """Total extracted capacitance (fF) on each port net, and resistor count, from the same Magic flow."""
    cap = (folder / f"{name}_cap.spice").read_text()
    pex = (folder / f"{name}_pex.spice").read_text()
    ports = re.search(rf"(?im)^\.subckt\s+{name}\s+(.+)", cap)[1].split()
    c = defaultdict(float)
    for line in cap.splitlines():
        if re.match(r"^C\S*\s", line):
            _, a, b, value = line.split()[:4]
            value = float(re.sub(r"[fF]$", "", value)) * (1 if value.lower().endswith("f") else 1e15)
            for n in (a, b):
                if n in ports:
                    c[n] += value
    r = defaultdict(float)
    for line in pex.splitlines():
        if re.match(r"^R\S*\s", line):
            _, a, b, value = line.split()[:4]
            r[a.split(".")[0]] += float(value)
    return {"cap_fF": {k: round(v, 4) for k, v in c.items()}, "res_ohm": {k: round(v, 2) for k, v in r.items()}}


def hd_reference(work: Path, short: str) -> Path:
    """The installed cell, alone in a GDS and extracted with our Magic flow."""
    name = PREFIX + short
    work.mkdir(parents=True, exist_ok=True)
    layout = kdb.Layout()
    layout.read(str(HD_GDS))
    options = kdb.SaveLayoutOptions()
    options.select_cell(layout.cell(name).cell_index())
    layout.write(str(work / f"{name}.gds"), options)
    text = HD_SPICE.read_text()
    start = text.index(f".subckt {name} ")
    (work / f"{name}.spice").write_text(text[start:text.index(".ends", start) + 5] + "\n")
    ports = text[start:].splitlines()[0].split()[2:]
    if not (work / f"{name}_pex.spice").exists():
        magic_extract(work, name, ports)
    return work


def picture(path: Path, cells: list):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon, Rectangle
    colours = {(64, 20): ("#c8c8ff", .3), (65, 20): ("#2e9e2e", .6), (66, 20): ("#d62728", .6),
               (66, 44): ("#000000", .9), (67, 20): ("#9467bd", .45), (67, 44): ("#444444", .9),
               (68, 20): ("#1f77b4", .35), (95, 20): ("#ff7f0e", .15)}
    fig, axes = plt.subplots(1, len(cells), figsize=(4 * len(cells), 6))
    for ax, (title, (layout, cell)) in zip(axes, cells):
        for layer, (colour, alpha) in colours.items():
            for p in region(layout, cell, layer).merged().each():
                points = [(q.x * layout.dbu, q.y * layout.dbu) for q in p.each_point_hull()]
                ax.add_patch(Polygon(points, color=colour, alpha=alpha, lw=0))
        bb = region(layout, cell, (236, 0)).bbox().to_dtype(layout.dbu)
        ax.add_patch(Rectangle((bb.left, bb.bottom), bb.width(), bb.height(), fill=False, ls="--", lw=1))
        ax.set_xlim(-0.3, 2.2)
        ax.set_ylim(-0.35, 3.05)
        ax.set_aspect("equal")
        ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def compare(folder: Path, name: str, short: str) -> dict:
    hd_dir = hd_reference(folder.parent / "hd", short)
    hd_name = PREFIX + short
    ours, theirs = load(folder / f"{name}.gds"), load(hd_dir / f"{hd_name}.gds", hd_name)
    width = lambda lc: round(region(*lc, (236, 0)).bbox().width() * lc[0].dbu, 3)
    w_ours, w_hd = width(ours), width(theirs)
    result = {
        "cell": name, "hd": hd_name,
        "frame": {"expected": expected_frame(), "ours": frame(*ours), "hd": frame(*theirs)},
        "xor_um2": xor(ours, theirs) if abs(w_ours - w_hd) < TOL else "widths differ",
        "lvs_vs_hd": "match" if lvs(folder, f"{name}_lvs", name, str(hd_dir / f"{hd_name}.spice"), hd_name) else "fail",
        "pins": {"ours": pins(*ours), "hd": pins(*theirs)},
        "wiring": {"ours": wiring(*ours), "hd": wiring(*theirs)},
        "width_sites": {"ours": round(w_ours / 0.46), "hd": round(w_hd / 0.46)},
        "gates": {"ours": gates(*ours), "hd": gates(*theirs)},
        "parasitics": {"ours": parasitics(folder, name), "hd": parasitics(hd_dir, hd_name)},
    }
    result["frame"]["match"] = all(
        result["frame"]["ours"][k] is not None and abs(result["frame"]["ours"][k][0] - v[0]) < TOL
        and abs(result["frame"]["ours"][k][1] - v[1]) < TOL for k, v in expected_frame().items())
    picture(folder / f"{name}_vs_hd.png", [(name, ours), (hd_name, theirs)])
    (folder / f"{name}_compare.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    folder = Path(sys.argv[1]).resolve()
    r = compare(folder.parent, folder.name, sys.argv[2])
    print(f"frame: {'match' if r['frame']['match'] else 'DIFFERS'}   xor: {r['xor_um2']}")
    print(f"transistors (LVS vs HD): {r['lvs_vs_hd']}")
    print(f"width: {r['width_sites']['ours']} sites, HD {r['width_sites']['hd']}")
    print(f"wiring: ours {r['wiring']['ours']}   HD {r['wiring']['hd']}")
    for who in ("ours", "hd"):
        g = r["gates"][who]
        print(f"gates {who:4s}: order {g['order']} at {g['gate_x']}, pitch {g['pitch']}, breaks {g['diffusion_breaks']}")
    for who in ("ours", "hd"):
        print(f"pins {who:4s}: " + "; ".join(f"{k} {v[0]['layer']}/{v[0]['band']}/{v[0]['size']}" for k, v in sorted(r["pins"][who].items())))
    for who in ("ours", "hd"):
        print(f"C (fF) {who:4s}: {r['parasitics'][who]['cap_fF']}")
