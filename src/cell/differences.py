"""Table 4 for the six reference cells, written from the files that hold it (option 1 handout, section 4.1
and 8.2): every row of the comparison with the installed HD cell, so the document never drifts from the cells.

    python -m src.cell.differences      -> results/differences_vs_hd.md

Sources: cells/dd2_gc1__<cell>/report.json (key compare, from src/cell/compare.py) and results/timing_vs_hd.csv
(both cells characterized by our flow, src/cell/timing_vs_hd.py). The pictures are cells/<cell>/vs_hd.png.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CELLS = ["inv_1", "nand2_1", "nor2_1", "nand3_1", "a21oi_1", "o21ai_1"]
OUT = ROOT / "results/differences_vs_hd.md"


def timing() -> dict:
    """cell -> (slowest arc ours, HD's, input capacitance differences in %), at the point of section 6."""
    arcs, caps = defaultdict(list), defaultdict(list)
    for r in csv.DictReader((ROOT / "results/timing_vs_hd.csv").open()):
        if r["value"] == "capacitance":
            caps[r["cell"]].append(float(r["diff_pct"]))
        elif r["value"].startswith("cell_"):
            arcs[r["cell"]].append((float(r["ours"]), float(r["hd_our_flow"])))
    return {c: (max(o for o, _ in a), max(h for _, h in a), caps[c]) for c, a in arcs.items()}


def pins(side: dict) -> str:
    inputs = {p: shapes for p, shapes in side.items() if p not in ("Y", "VGND", "VPWR", "VPB", "VNB")}
    off = sorted(p for p, shapes in inputs.items() if any(s["band"] != "npc" for s in shapes))
    return "all in the npc band" if not off else f"{', '.join(off)} in a row band"


def main():
    t = timing()
    lines = ["# Our reference cells against the installed HD cells (Table 4)", "",
             "Written by `python -m src.cell.differences` from `cells/dd2_gc1__<cell>/report.json` (key `compare`) and",
             "`results/timing_vs_hd.csv`; the side-by-side pictures are `cells/dd2_gc1__<cell>/vs_hd.png`. Timing is at",
             "the HD table point nearest 100 ps and 10 fF, both cells characterized by our flow. The version written",
             "by hand at checkpoint 2 is `results/differences_vs_hd_cp2.md`.", "",
             "| Cell | Frame (XOR um2) | Transistors (LVS vs HD) | Pins, ours / HD | Wiring | Sites ours / HD | "
             "Gate order ours / HD (NMOS row) | Gate pitch ours / HD (um) | Y cap ours / HD (fF) | Slowest arc ours / HD (ns) | "
             "Input cap vs HD |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    notes = []
    for short in CELLS:
        name = f"dd2_gc1__{short}"
        r = json.loads((ROOT / "cells" / name / "report.json").read_text())["compare"]
        xor = max(r["xor_um2"].values()) if isinstance(r.get("xor_um2"), dict) else None    # a string when widths differ
        frame = ("match" if r["frame"]["match"] else "differs") + (f" ({xor:g})" if xor is not None else " (widths differ)")
        g = r["gates"]
        wiring = "li1 inside, met1 rails only" if r["wiring"]["ours"]["met1_only_rails"] else "met1 inside"
        y = r["parasitics"]["ours"]["cap_fF"].get("Y"), r["parasitics"]["hd"]["cap_fF"].get("Y")
        slow, hd, caps = t[name]
        lines.append(f"| {short} | {frame} | {r['lvs_vs_hd']} | {pins(r['pins']['ours'])} / {pins(r['pins']['hd'])} | "
                     f"{wiring} | {r['width_sites']['ours']} / {r['width_sites']['hd']} | "
                     f"{' '.join(g['ours']['n']['order'])} / {' '.join(g['hd']['n']['order'])} | "
                     f"{', '.join(map(str, g['ours']['n']['pitch']))} / {', '.join(map(str, g['hd']['n']['pitch']))} | "
                     f"{y[0]} / {y[1]} | {slow:.4f} / {hd:.4f} ({(slow - hd) / hd * 100:+.1f}%) | "
                     f"{min(caps):+.1f} to {max(caps):+.1f}% |")
        if r["width_sites"]["ours"] > r["width_sites"]["hd"]:
            notes.append(f"- **{short}** is {r['width_sites']['ours'] - r['width_sites']['hd']} site wider. Pins: ours "
                         f"{pins(r['pins']['ours'])}, HD {pins(r['pins']['hd'])}; NMOS gate pitch ours "
                         f"{g['ours']['n']['pitch']} against HD's {g['hd']['n']['pitch']} um.")
        if g["ours"]["n"]["order"] != g["hd"]["n"]["order"]:
            notes.append(f"- **{short}**: gate order {' '.join(g['ours']['n']['order'])} against HD's "
                         f"{' '.join(g['hd']['n']['order'])}.")
    must = []
    for short in CELLS:
        name = f"dd2_gc1__{short}"
        r = json.loads((ROOT / "cells" / name / "report.json").read_text())["compare"]
        abut = json.loads((ROOT / "cells" / name / "response.json").read_text())["checks"]["abutment"]
        must.append(r["frame"]["match"] and r["lvs_vs_hd"] == "match" and pins(r["pins"]["ours"]) == "all in the npc band"
                    and r["wiring"]["ours"]["met1_only_rails"] and abut == 0)
    verdict = ("matches for all six cells" if all(must) else
               "does NOT match for " + ", ".join(c for c, ok in zip(CELLS, must) if not ok))
    lines += ["", "Every row marked \"must match\" in Table 4 (frame, transistors, our input pins on li1 in the npc band, "
              f"li1 wiring with met1 only on the rails, abutment with 0 DRC errors): {verdict}.", "",
              "## Differences to explain", ""] + (notes or ["- none"])
    OUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
