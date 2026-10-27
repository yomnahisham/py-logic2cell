
"""Pull the reference cells out of the combined PDK files into build/ref/ (not committed)."""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))

import klayout.db as db
import re
from pathlib import Path
from paths import GDS, LEF, SPICE, PREFIX, REFERENCE_CELLS, ROOT

OUT = ROOT / "build" / "ref"


def extract_block(path, is_start, is_end):
    """Copy lines from the first matching start line through the first matching end line."""
    out, on = [], False
    with open(path) as f:
        for line in f:
            if not on and is_start(line.strip()):
                on = True
            if on:
                out.append(line)
                if is_end(line.strip()):
                    break
    return "".join(out)


def get_lef_size(lef_text):
    """Return (width, height) from an extracted LEF MACRO's SIZE statement."""
    match = re.search(
        r"^\s*SIZE\s+([\d.]+)\s+BY\s+([\d.]+)\s*;",
        lef_text,
        re.MULTILINE | re.IGNORECASE,
    )

    if not match:
        raise ValueError("No valid SIZE statement found in LEF macro")

    return float(match.group(1)), float(match.group(2))


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    layout = db.Layout()
    layout.read(str(GDS))
    boundary = layout.find_layer(236, 0)  # prBoundary

    for short in REFERENCE_CELLS:
        name = PREFIX + short

        spice = extract_block(
            SPICE,
            lambda s: s.startswith(f".subckt {name} "),
            lambda s: s.startswith(".ends"),
        )
        lef = extract_block(
            LEF,
            lambda s: s == f"MACRO {name}",
            lambda s: s == f"END {name}",
        )

        (OUT / f"{short}.spice").write_text(spice)
        (OUT / f"{short}.lef").write_text(lef)

        cell = layout.cell(name)
        if cell is None:
            print(f"{short}: NOT FOUND in GDS")
            continue

        cell.write(str(OUT / f"{short}.gds"))

        # Prefer the GDS prBoundary if it has valid positive dimensions.
        box = cell.bbox_per_layer(boundary).to_dtype(layout.dbu)
        width, height = box.width(), box.height()
        source = "GDS boundary"

        # Fall back to the LEF SIZE when the GDS boundary is missing/invalid.
        if width <= 0 or height <= 0:
            try:
                width, height = get_lef_size(lef)
                source = "LEF SIZE fallback"
            except ValueError as e:
                print(f"{short}: could not determine dimensions: {e}")
                continue

        print(
            f"{short}: spice {len(spice.splitlines())} lines, "
            f"lef {len(lef.splitlines())} lines, "
            f"boundary {width:.2f} x {height:.2f} um ({source})"
        )


if __name__ == "__main__":
    main()
