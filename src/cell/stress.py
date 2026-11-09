"""SA and SB, the BSIM4 stress distances, measured from a cell's GDS and written into its extracted netlist
(option 1 handout, section 5).

    python -m src.cell.stress <work dir> <cell name> [--probe]

SA and SB of a finger are the distances from the two sides of its gate to the ends of its diffusion strip,
measured through any neighbouring gates. Magic's extraction does not write them, so each transistor of
<name>_pex.spice is matched to its finger in <name>.gds (by type, gate input and width) and given its SA and
SB; the result is <name>_sasb.spice. --probe asks ngspice what W, L, SA and SB each device ended up with.

A strip whose edge jogs under a gate is cut into horizontal slices, and the slices are combined as BSIM4
combines the segments of a non-rectangular diffusion: 1/(SA + L/2) averaged over the width.
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
SUFFIX = {"t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15}


def spice_number(text: str) -> float:
    m = re.fullmatch(r"([-+]?[\d.]+(?:[eE][-+]?\d+)?)(meg|[tgkmunpf])?[a-zA-Z]*", text.strip(), re.I)
    if not m:
        raise ValueError(f"not a SPICE number: {text!r}")
    return float(m[1]) * SUFFIX.get((m[2] or "").lower(), 1)


def _region(layout, cell, layer):
    index = layout.find_layer(*layer)
    return kdb.Region(cell.begin_shapes_rec(index)) if index is not None else kdb.Region()


def gate_owners(layout, cell) -> list[tuple[kdb.Polygon, str]]:
    """Each poly shape, and the input whose li label reaches a poly contact on it ("?" if none). The label
    reaches along li, and across met1 where li pieces are bridged through mcon (a multi-stage cell routes a
    net on met1 where li cannot, as in mux2_1)."""
    from src.cell.layout import LAYER
    poly = list(_region(layout, cell, POLY).merged().each())
    li = list(_region(layout, cell, LI).merged().each())
    licon = _region(layout, cell, LICON)
    mcon = _region(layout, cell, LAYER["mcon"])
    group = list(range(len(li)))           # li pieces joined through mcon and one met1 shape

    def root(i):
        while group[i] != i:
            i = group[i]
        return i
    for m in _region(layout, cell, LAYER["met1"]).merged().each():
        cuts = mcon & kdb.Region(m)
        touched = [i for i, w in enumerate(li) if not (kdb.Region(w) & cuts).is_empty()]
        for i in touched[1:]:
            group[root(i)] = root(touched[0])
    owner = {}
    index = layout.find_layer(*LI_LABEL)
    for s in (cell.shapes(index).each() if index is not None else []):
        if not s.is_text():
            continue
        point = kdb.Point(s.text_pos.x, s.text_pos.y)
        hit = {root(i) for i, w in enumerate(li) if w.inside(point)}
        wires = kdb.Region([w for i, w in enumerate(li) if root(i) in hit])
        for i, shape in enumerate(poly):
            if not (kdb.Region(shape) & licon & wires).is_empty():
                owner[i] = s.text_string
    return [(shape, owner.get(i, "?")) for i, shape in enumerate(poly)]


def fingers(gds: Path, top: str | None = None) -> list[dict]:
    """Every transistor finger in the layout: type, gate input, x, W, L, SA, SB (um)."""
    layout = kdb.Layout()
    layout.read(str(gds))
    cell = layout.cell(top) if top and layout.cell(top) else layout.top_cell()
    dbu = layout.dbu
    diff = _region(layout, cell, DIFF).merged()
    nwell = _region(layout, cell, NWELL)
    owners = gate_owners(layout, cell)
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


def ext_devices(ext: Path, found: list[dict]) -> list[tuple]:
    """(kind, gate, terminal nets, gate centre x in um) of every transistor in Magic's .ext file. Lengths
    there are in Magic's internal unit, found from a gate length (the layout's L over the .ext's l)."""
    out = []
    if not ext.exists():
        return out
    for line in ext.read_text().splitlines():
        m = re.match(r'device msubckt sky130_fd_pr__([np])fet\S* (-?\d+) -?\d+ -?\d+ -?\d+ l=(\d+) w=\d+ "[^"]*" "([^"]+)" '
                     r'\d+ \d+ "([^"]+)" \d+ \S+ "([^"]+)"', line)
        if m:
            kind, x, l, gate, t1, t2 = m.groups()
            unit = found[0]["l"] / int(l)
            out.append((kind, gate.rstrip("#"), frozenset(t.rstrip("#") for t in (t1, t2)), round((int(x) + int(l) / 2) * unit, 4)))
    return out


def annotate(netlist: Path, found: list[dict], out: Path, ext: list[tuple] = ()) -> list[dict]:
    """Copy netlist to out with sa= and sb= on every transistor. Returns what each device was given.

    SA and SB are written in the same units as that line's w= (Magic may write w in um with a scale
    option, or in metres), so they mean what W means; --probe checks this inside ngspice."""
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
        if len({(f["sa"], f["sb"]) for f in match}) > 1:
            # fingers of one input with different SA/SB: tell them apart by where Magic found the device
            nets = {re.sub(r"\.t\d+$", "", t) for t in (tok[1], tok[3])}
            at = [x for k, g, terms, x in ext if (k, g, terms) == (kind, gate, frozenset(nets))]
            if len(set(at)) != 1:
                raise ValueError(f"{netlist.name}: {tok[0]} matches fingers with different SA/SB: {match}, "
                                 f"and {len(at)} devices in the .ext with its gate and terminals")
            match = [min(match, key=lambda f: abs(f["x"] - at[0]))]
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
    found = fingers(folder / f"{name}.gds", name)
    ext = ext_devices(folder / f"{name}.ext", found)
    # a gate on a net with no label (an installed HD cell labels only its pins) takes the net Magic found
    # for the device at the same place
    for f in found:
        if f["gate"] == "?":
            at = {g for k, g, _, x in ext if k == f["kind"] and abs(x - f["x"]) < 1e-3}
            if len(at) == 1:
                f["gate"] = at.pop()
    given = annotate(folder / f"{name}_pex.spice", found, folder / f"{name}_sasb.spice", ext)
    (folder / f"{name}_sasb.json").write_text(json.dumps(dict(fingers=found, devices=given), indent=2) + "\n")
    return given


if __name__ == "__main__":
    folder, name = Path(sys.argv[1]).resolve(), sys.argv[2]
    for f in fingers(folder / f"{name}.gds", name):
        print(f"finger {f['kind']} gate {f['gate']:4s} x {f['x']:6.3f}  W {f['w']}  L {f['l']}  SA {f['sa']}  SB {f['sb']}")
    for d in stress(folder, name):
        print(f"device {d['device']:6s} {d['kind']} gate {d['gate']:4s} sa {d['sa']} sb {d['sb']}")
    print(f"-> {folder / f'{name}_sasb.spice'}")
    if "--probe" in sys.argv:
        print(probe(folder, name))
