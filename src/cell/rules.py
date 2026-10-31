"""The design rule behind every number in the layout plan, checked against the PDK decks.

    python -m src.cell.rules          -> results/design_rules.csv
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

from src.cell import layout as lay

ROOT = Path(__file__).resolve().parents[2]
MAGIC = ROOT / "pdk/libs.tech/magic/sky130A.tech"
KLAYOUT = ROOT / "pdk/libs.tech/klayout/drc/sky130A.lydrc"
OUT = ROOT / "results/design_rules.csv"

# (what, constant in layout.py, rule, words in the deck's message that pick the right statement)
EXACT = [
    ("gate length", "L", "poly.1a", "poly width"),
    ("poly spacing", "POLY_SPACE", "poly.2", "poly spacing"),
    ("poly past diffusion (endcap)", "ENDCAP", "poly.8", "poly overhang of transistor"),
    ("contact size", "CUT", "licon.1", "P-diffusion contact width"),
    ("contact to standard cell gate", "CUT_GATE", "licon.11", "standard cell gate"),
    ("diffusion around contact", "CUT_DIFF", "licon.5a", "N-diffusion overlap"),
    ("diffusion around contact, one direction", "CUT_DIFF_DIR", "licon.5c", "P-diffusion overlap of P-diffusion contact"),
    ("poly around poly contact", "POLY_CUT", "licon.8", "poly overlap of poly contact <"),
    ("poly around poly contact, one direction", "POLY_CUT_DIR", "licon.8a", "poly overlap of poly contact"),
    ("diffusion spacing", "DIFF_SPACE", "diff/tap.3", "Diffusion spacing"),
    ("li width", "LI", "li.1", "Local interconnect width"),
    ("li spacing", "LI_SPACE", "li.3", "Local interconnect spacing"),
    ("li around contact, one direction", "LI_CUT_DIR", "li.5", "overlap of poly contact"),
    ("npc around poly contact", "NPC_CUT", "licon.15", None),
]


def magic_value(rule: str, words: str) -> float:
    """The value (um) of the statement whose message names `rule` and contains `words`."""
    text = MAGIC.read_text()
    for m in re.finditer(r'"([^"]*\(' + re.escape(rule) + r'\))"', text):
        if words in m.group(1):
            start = text.rfind("\n ", 0, m.start())
            statement = text[start:m.start()]
            return int(re.findall(r"\s(\d+)\s", statement)[-1]) / 1000
    raise LookupError(f"{rule} ({words}) not found in {MAGIC.name}")


def klayout_value(rule: str) -> float:
    m = re.search(re.escape(rule) + r" : [^\"]*: ([\d.]+)um", KLAYOUT.read_text())
    return float(m[1])


def rows() -> list[dict]:
    out = []
    for what, name, rule, words in EXACT:
        pdk = klayout_value(rule) if words is None else magic_value(rule, words)
        value = getattr(lay, name)
        out.append(dict(what=what, value=value, rule=rule, pdk=pdk, ok=abs(value - pdk) < 1e-9, how="equal"))

    def derived(what, value, rule, pdk, how):
        out.append(dict(what=what, value=round(value, 4), rule=rule, pdk=round(pdk, 4),
                        ok=value >= pdk - 1e-9, how=how))

    cut, gate, poly = magic_value("licon.1", "P-diffusion contact width"), \
        magic_value("licon.11", "standard cell gate"), magic_value("poly.1a", "poly width")
    derived("gate pitch over a contacted column", lay.L + 2 * lay.CUT_GATE + lay.CUT,
            "poly.1a + 2 licon.11 + licon.1", poly + 2 * gate + cut, ">=")
    derived("gate pitch over shared diffusion", lay.L + lay.POLY_SPACE, "poly.1a + poly.2",
            poly + magic_value("poly.2", "poly spacing"), ">=")
    derived("contact pitch", lay.CUT_PITCH, "licon.1 + licon.2",
            cut + magic_value("licon.2", "Diffusion contact spacing"), ">=")
    derived("poly contact to NMOS diffusion", lay.PAD_CUT[0] - lay.N_DIFF[1], "licon.14",
            magic_value("licon.14", "poly contact spacing to diffusion"), ">=")
    derived("poly contact pad to NMOS diffusion", lay.PAD_POLY[0] - lay.N_DIFF[1], "poly.4",
            magic_value("poly.4", "poly spacing to Diffusion"), ">=")
    derived("input pin li area", (lay.PAD_LI[1] - lay.PAD_LI[0]) * 2 * lay.PAD_HALF, "li.6 (um2)",
            int(re.search(r"area allli,\*obsli (\d+)", MAGIC.read_text())[1]) / 1e6, ">=")
    derived("input pin li to NMOS row li", lay.PAD_LI[0] - lay.N_LI[1], "li.3",
            magic_value("li.3", "Local interconnect spacing"), ">=")
    derived("input pin li to PMOS row li", lay.P_LI[0] - lay.PAD_LI[1], "li.3",
            magic_value("li.3", "Local interconnect spacing"), ">=")
    return out


def main() -> int:
    table = rows()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["what", "value", "how", "pdk", "rule", "ok"])
        w.writeheader()
        w.writerows(table)
    for r in table:
        print(f"{'ok ' if r['ok'] else 'BAD'} {r['what']:42s} {r['value']:<8g} {r['how']:5s} {r['pdk']:<8g} {r['rule']}")
    return 0 if all(r["ok"] for r in table) else 1


if __name__ == "__main__":
    sys.exit(main())
