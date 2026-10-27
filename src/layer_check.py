"""Layer check: implants over diffusion, npc over poly contacts. Usage: layer_check.py cell.gds [cell_name]"""
import sys
import klayout.db as db

L = {"diff": (65, 20), "poly": (66, 20), "licon1": (66, 44), "nwell": (64, 20),
     "nsdm": (93, 44), "psdm": (94, 20), "hvtp": (78, 44), "npc": (95, 20)}


def region(layout, cell, key):
    idx = layout.find_layer(*L[key])
    return db.Region(cell.begin_shapes_rec(idx)) if idx is not None else db.Region()


def check(gds, cell_name=None):
    layout = db.Layout()
    layout.read(gds)
    cell = layout.cell(cell_name) if cell_name else layout.top_cell()
    r = {k: region(layout, cell, k) for k in L}
    fails = []

    channels = r["diff"].interacting(r["poly"])          # transistor diffusion only
    pmos = channels.inside(r["nwell"])
    nmos = channels - pmos
    pmos = channels.interacting(r["nwell"]) if pmos.is_empty() else pmos
    nmos = channels - pmos

    if not (pmos - r["psdm"]).is_empty():
        fails.append("PMOS diffusion not fully covered by psdm")
    if not (pmos - r["hvtp"]).is_empty():
        fails.append("PMOS diffusion not fully covered by hvtp")
    if not (nmos - r["nsdm"]).is_empty():
        fails.append("NMOS diffusion not fully covered by nsdm")

    poly_contacts = r["licon1"].interacting(r["poly"]) - r["licon1"].interacting(r["diff"])
    if not (poly_contacts - r["npc"]).is_empty():
        fails.append("poly contact not covered by npc")

    print(f"{cell.name}: pmos={pmos.count()} nmos={nmos.count()} poly_contacts={poly_contacts.count()}")
    for f in fails:
        print("  FAIL:", f)
    return not fails


if __name__ == "__main__":
    ok = check(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
