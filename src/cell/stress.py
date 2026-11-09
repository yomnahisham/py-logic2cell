"""SA and SB, the BSIM4 stress distances, measured from a cell's GDS and written into its extracted netlist
(option 1 handout, section 5).

    python -m src.cell.stress <work dir> <cell name> [--probe]

SA and SB of a finger are the distances from the two sides of its gate to the ends of its diffusion strip,
measured through any neighbouring gates. Magic's extraction does not write them, so each transistor of
<name>_pex.spice is matched to its finger in <name>.gds (by type, gate input and width) and given its SA and
SB; the result is <name>_sasb.spice. When an input drives two fingers of the same width with different SA/SB
(xor2, mux2), the device is matched by position: <name>.res.ext, the file Magic writes <name>_pex.spice from,
gives each device's gate terminal (e.g. A.t1, as in the netlist) and the left edge of its gate, in MAGIC_UNIT. --probe asks ngspice what W, L, SA and SB each device ended up with.

A strip whose edge jogs under a gate is cut into horizontal slices, and the slices are combined as BSIM4
combines the segments of a non-rectangular diffusion: 1/(SA + L/2) averaged over the width.

A gate is named by the net that drives it. A gate driven by an input carries that input's label (li or met1). A gate driven from inside the cell (the next
stage of a multi-stage cell) has no label; Magic names its net a_<x>_<y> after a point on the net, in units
of MAGIC_UNIT, and the gate is named the same way: the net found at that point, through poly, diffusion,
licon, li, mcon and met1, that carries no label.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import klayout.db as kdb

from src.cell.tools import MODELS, run

DIFF, POLY, NWELL, LI, LICON, LI_LABEL = (65, 20), (66, 20), (64, 20), (67, 20), (66, 44), (67, 5)
MCON, MET1, MET1_LABEL = (67, 44), (68, 20), (68, 5)
# um; Magic's internal unit in the sky130 tech file. Checked on a21o, mux2, xor2 and and2: every a_<x>_<y> point
# falls on an edge of its net (poly end at y = 0.105, diffusion bottoms at y = 0.235 and 1.485)
MAGIC_UNIT = 0.005
SUFFIX = {"t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15}


def spice_number(text: str) -> float:
    m = re.fullmatch(r"([-+]?[\d.]+(?:[eE][-+]?\d+)?)(meg|[tgkmunpf])?[a-zA-Z]*", text.strip(), re.I)
    if not m:
        raise ValueError(f"not a SPICE number: {text!r}")
    return float(m[1]) * SUFFIX.get((m[2] or "").lower(), 1)


def _region(layout, cell, layer):
    index = layout.find_layer(*layer)
    return kdb.Region(cell.begin_shapes_rec(index)) if index is not None else kdb.Region()


def inner_gate_nets(netlist: Path) -> list[str]:
    """The gate nets of a Magic netlist that Magic named after a point (a_<x>_<y>), not after a label."""
    gates = set()
    for line in netlist.read_text().replace("\n+", " ").splitlines():
        tok = line.split()
        if tok and tok[0][0] in "Xx" and len(tok) > 5 and "fet" in tok[5]:
            gates.add(tok[2].split(".")[0])
    return sorted(g for g in gates if re.fullmatch(r"a_\d+_\d+", g))


def _nets(layout, cell):
    """The cell's connectivity, as Magic extracts it: poly, source/drain diffusion (diffusion outside poly), licon,
    li, mcon and met1, with the contacts joining the layers above and below them."""
    l2n = kdb.LayoutToNetlist(kdb.RecursiveShapeIterator(layout, cell, []))
    layer = {k: l2n.make_layer(layout.layer(*spec), k) for k, spec in
             dict(diff=DIFF, poly=POLY, licon=LICON, li=LI, mcon=MCON, met1=MET1).items()}
    layer["sd"] = layer["diff"] - layer["poly"]
    l2n.register(layer["sd"], "sd")
    for k in ("poly", "sd", "licon", "li", "mcon", "met1"):
        l2n.connect(layer[k])
    for a, b in (("poly", "licon"), ("sd", "licon"), ("licon", "li"), ("li", "mcon"), ("mcon", "met1")):
        l2n.connect(layer[a], layer[b])
    l2n.extract_netlist()
    return l2n, layer


def gate_owners(layout, cell, inner: list[str] = ()) -> list[tuple[kdb.Polygon, str]]:
    """Each poly shape, and the name of the net that drives it: the input label on that net, or for an inner
    gate its Magic name from inner (see the module docstring); "?" if neither."""
    poly = list(_region(layout, cell, POLY).merged().each())
    l2n, layer = _nets(layout, cell)
    dbu = layout.dbu
    owner, labelled = {}, set()

    def claim(net, name):
        hits = [i for i, shape in enumerate(poly)
                if not (kdb.Region(shape) & l2n.shapes_of_net(net, layer["poly"], True)).is_empty()]
        for i in hits:
            if owner.get(i, name) != name:
                raise ValueError(f"{cell.name}: one gate is driven by both {owner[i]} and {name}")
            owner[i] = name
        return hits

    # labelled nets: the inputs, Y and the supplies (the last two drive no poly)
    for spec, on in ((LI_LABEL, "li"), (MET1_LABEL, "met1")):
        index = layout.find_layer(*spec)
        for s in (cell.shapes(index).each() if index is not None else []):
            if s.is_text():
                net = l2n.probe_net(layer[on], kdb.DPoint(s.text_pos.x * dbu, s.text_pos.y * dbu))
                if net is not None:
                    labelled.add(net.cluster_id)
                    claim(net, s.text_string)

    for name in inner:
        x, y = (int(v) * MAGIC_UNIT for v in name[2:].split("_"))
        found = {}
        # the point is a corner of a shape of the net; look just inside it, on every layer it may be on
        for dx in (1, -1):
            for dy in (1, -1):
                point = kdb.DPoint(x + dx * dbu, y + dy * dbu)
                for on in ("poly", "sd", "li", "met1"):
                    net = l2n.probe_net(layer[on], point)
                    if net is not None and net.cluster_id not in labelled:
                        found[net.cluster_id] = net
        if len(found) != 1:
            raise ValueError(f"{cell.name}: Magic net {name} at ({x:.3f}, {y:.3f}) um matches {len(found)} unlabelled "
                             f"nets in the layout, expected 1")
        if not claim(next(iter(found.values())), name):
            raise ValueError(f"{cell.name}: Magic net {name} is a gate in the netlist but reaches no poly")
    return [(shape, owner.get(i, "?")) for i, shape in enumerate(poly)]


def fingers(gds: Path, top: str | None = None, inner: list[str] = ()) -> list[dict]:
    """Every transistor finger in the layout: type, gate input, x, W, L, SA, SB (um). inner: the netlist's
    point-named gate nets (inner_gate_nets), so the gates of inner stages are named too."""
    layout = kdb.Layout()
    layout.read(str(gds))
    cell = layout.cell(top) if top and layout.cell(top) else layout.top_cell()
    dbu = layout.dbu
    diff = _region(layout, cell, DIFF).merged()
    nwell = _region(layout, cell, NWELL)
    owners = gate_owners(layout, cell, inner)
    out = []
    for gate in (_region(layout, cell, POLY).merged() & diff).each():
        gb = gate.bbox()
        if gate.num_points() != 4:
            raise ValueError(f"{gds}: gate at {gb.to_dtype(dbu)} is not a rectangle")
        strip = next(p for p in diff.each() if p.bbox().contains(gb.center()) and
                     not (kdb.Region(p) & kdb.Region(gate)).is_empty())
        kind = "p" if (kdb.Region(gate) - nwell).is_empty() else "n"
        name = next((n for shape, n in owners if not (kdb.Region(shape) & kdb.Region(gate)).is_empty()), "?")
        length, width = gb.width() * dbu, gb.height() * dbu
        # slice the strip at every y where its outline turns, inside the gate's y range
        ys = sorted({gb.bottom, gb.top} | {pt.y for pt in strip.each_point_hull() if gb.bottom < pt.y < gb.top})
        inv_sa = inv_sb = 0.0
        for y0, y1 in zip(ys, ys[1:]):
            band = kdb.Region(strip) & kdb.Region(kdb.Box(strip.bbox().left - 1, y0, strip.bbox().right + 1, y1))
            piece = next(p for p in band.each() if p.bbox().left <= gb.left and p.bbox().right >= gb.right)
            sa = (gb.left - piece.bbox().left) * dbu
            sb = (piece.bbox().right - gb.right) * dbu
            share = (y1 - y0) * dbu / width
            inv_sa += share / (sa + length / 2)
            inv_sb += share / (sb + length / 2)
        out.append(dict(kind=kind, gate=name, x=round(gb.center().x * dbu, 4), w=round(width, 4),
                        l=round(length, 4), sa=round(1 / inv_sa - length / 2, 4), sb=round(1 / inv_sb - length / 2, 4)))
    return sorted(out, key=lambda f: (f["kind"], f["x"]))


def device_positions(res_ext: Path) -> dict[tuple[str, str], list[float]]:
    """(type, gate terminal) of each device in Magic's .res.ext (e.g. ("n", "A.t1")) -> x of the left edge of
    the gate (um), for every device with that type and terminal (one, unless the gate net was not split)."""
    out = {}
    for line in res_ext.read_text().splitlines():
        tok = line.split()
        if tok[:2] != ["device", "msubckt"]:
            continue
        gate = re.findall(r'"([^"]*)"', line)[1]               # the first quoted name is the body, then the gate
        kind = "p" if "pfet" in tok[2] else "n"
        out.setdefault((kind, gate), []).append(int(tok[3]) * MAGIC_UNIT)
    return out


def annotate(netlist: Path, found: list[dict], out: Path,
             positions: dict[tuple[str, str], list[float]] | None = None) -> list[dict]:
    """Copy netlist to out with sa= and sb= on every transistor. Returns what each device was given.

    SA and SB are written in the same units as that line's w= (Magic may write w in um with a scale
    option, or in metres), so they mean what W means; --probe checks this inside ngspice.
    positions (device_positions): (type, gate terminal) -> left edge of the gate, used when type, gate and
    width leave more than one finger with different SA/SB."""
    lines = netlist.read_text().replace("\n+", " ").splitlines()
    devices = []
    for i, line in enumerate(lines):
        tok = line.split()
        if tok and tok[0][0] in "Xx" and len(tok) > 5 and "fet" in tok[5]:
            params = dict(t.split("=", 1) for t in tok[6:] if "=" in t)
            devices.append((i, tok, "p" if "pfet" in tok[5] else "n", tok[2].split(".")[0], spice_number(params["w"])))
    if not devices:
        raise ValueError(f"{netlist}: no transistors")

    # one scale for the whole file, from a device whose (type, gate) has a single finger
    count = Counter((f["kind"], f["gate"]) for f in found)
    unique = [(d, next(f for f in found if (f["kind"], f["gate"]) == (d[2], d[3])))
              for d in devices if count[(d[2], d[3])] == 1]
    if not unique:
        raise ValueError(f"{netlist}: no device matches a single finger, cannot tell the units of w")
    scale = unique[0][0][4] / unique[0][1]["w"]

    netlist_count = Counter((d[2], d[3]) for d in devices)
    if netlist_count != count:
        raise ValueError(f"{netlist.name}: transistors per (type, gate) differ: netlist {dict(netlist_count)}, "
                         f"layout {dict(count)}")
    given = []
    for i, tok, kind, gate, w in devices:
        match = [f for f in found if f["kind"] == kind and f["gate"] == gate and abs(w / scale - f["w"]) < 1e-3]
        if not match:
            raise ValueError(f"{netlist.name}: {tok[0]} ({kind}, gate {gate}, w {w / scale:g} um) has no finger")
        at = (positions or {}).get((kind, tok[2]), [])
        if len({(f["sa"], f["sb"]) for f in match}) > 1 and len(at) == 1:
            match = [f for f in match if abs(f["x"] - f["l"] / 2 - at[0]) < 1e-3]
            if len(match) != 1:
                raise ValueError(f"{netlist.name}: {tok[0]} at x {at[0]:.3f} um matches {len(match)} fingers, "
                                 f"expected 1")
        if len({(f["sa"], f["sb"]) for f in match}) > 1:
            raise ValueError(f"{netlist.name}: {tok[0]} matches fingers with different SA/SB: {match}")
        f = match[0]
        kept = [t for t in tok if not re.match(r"(?i)s[ab]=", t)]
        lines[i] = " ".join(kept + [f"sa={f['sa'] * scale:.6g}", f"sb={f['sb'] * scale:.6g}"])
        given.append(dict(device=tok[0], kind=kind, gate=gate, w=f["w"], l=f["l"], sa=f["sa"], sb=f["sb"]))
    out.write_text("\n".join(lines) + "\n")
    return given


def probe(folder: Path, name: str) -> str:
    """ngspice's own view of every MOSFET in <name>_sasb.spice: W, L, SA, SB as BSIM4 uses them (metres)."""
    text = (folder / f"{name}_sasb.spice").read_text()
    ports = re.search(rf"(?im)^\.subckt\s+{re.escape(name)}\s+(.+)", text)[1].split()
    nets = {p: "0" for p in ports}
    nets.update(VPWR="VPWR", VPB="VPWR")
    deck = [f"* {name}: W, L, SA, SB as ngspice sees them", f'.lib "{MODELS}" tt', f'.include "{name}_sasb.spice"',
            "VPWR VPWR 0 1.8", f"XU {' '.join(nets[p] for p in ports)} {name}",
            ".control", "op", "show m : w", "show m : l", "show m : sa", "show m : sb", "quit", ".endc", ".end"]
    (folder / f"{name}_probe.spice").write_text("\n".join(deck) + "\n")
    return run("ngspice", ["-b", f"{name}_probe.spice"], folder, folder / f"{name}_probe.log")


def stress(folder: Path, name: str) -> list[dict]:
    netlist = folder / f"{name}_pex.spice"
    found = fingers(folder / f"{name}.gds", name, inner_gate_nets(netlist))
    res_ext = folder / f"{name}.res.ext"
    positions = device_positions(res_ext) if res_ext.exists() else None
    given = annotate(netlist, found, folder / f"{name}_sasb.spice", positions)
    (folder / f"{name}_sasb.json").write_text(json.dumps(dict(fingers=found, devices=given), indent=2) + "\n")
    return given


if __name__ == "__main__":
    folder, name = Path(sys.argv[1]).resolve(), sys.argv[2]
    for f in fingers(folder / f"{name}.gds", name, inner_gate_nets(folder / f"{name}_pex.spice")):
        print(f"finger {f['kind']} gate {f['gate']:9s} x {f['x']:6.3f}  W {f['w']}  L {f['l']}  SA {f['sa']}  SB {f['sb']}")
    for d in stress(folder, name):
        print(f"device {d['device']:6s} {d['kind']} gate {d['gate']:9s} sa {d['sa']} sb {d['sb']}")
    print(f"-> {folder / f'{name}_sasb.spice'}")
    if "--probe" in sys.argv:
        print(probe(folder, name))
