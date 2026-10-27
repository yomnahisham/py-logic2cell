
"""Check the HD frame plan against Table 1 and installed reference-cell GDS."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import klayout.db as db
from paths import GDS, PREFIX, PLAN_HD as PLAN

TOL = 0.001  # um

# Table 1: required vertical extents, in micrometers.
TABLE1 = {
    "VGND rail": ((68, 20), -0.24, 0.24),
    "nsdm": ((93, 44), -0.19, 1.015),
    "npc": ((95, 20), 0.975, 1.345),
    "hvtp": ((78, 44), 1.25, 2.72),
    "nwell": ((64, 20), 1.305, 2.91),
    "psdm": ((94, 20), 1.355, 2.91),
    "VPWR rail": ((68, 20), 2.48, 2.96),
}

def close(a, b):
    return abs(a - b) <= TOL

def check(condition, message):
    status = "PASS" if condition else "FAIL"
    print(f"  {status}: {message}")
    return condition

def plan_layer(plan, key):
    return plan["frame"][key]["gds"]

def plan_y(plan, key):
    return plan["frame"][key]["y"]


def shape_boxes(cell, layer_index, dbu):
    """Return all non-degenerate shape bounding boxes in micrometers."""
    if layer_index is None:
        return []

    boxes = []
    for shape in cell.shapes(layer_index).each():
        b = shape.bbox()

        # Ignore empty or zero-area bounding boxes.
        if b.empty():
            continue
        if b.width() == 0 or b.height() == 0:
            continue

        boxes.append((
            b.left * dbu,
            b.bottom * dbu,
            b.right * dbu,
            b.top * dbu,
        ))

    return boxes


def has_y_band(boxes, ymin, ymax):
    """True if a shape has the expected vertical extent."""
    return any(close(b[1], ymin) and close(b[3], ymax) for b in boxes)

def main():
    if not PLAN.exists():
        raise FileNotFoundError(f"Plan not found: {PLAN}")
    if not GDS.exists():
        raise FileNotFoundError(f"Combined GDS not found: {GDS}")

    plan = json.loads(PLAN.read_text())
    layout = db.Layout()
    layout.read(str(GDS))
    dbu = layout.dbu
    frame = plan["frame"]

    passed = 0
    failed = 0

    def result(ok, message):
        nonlocal passed, failed
        if check(ok, message):
            passed += 1
        else:
            failed += 1

    print("=== 1. plan_hd.json vs Table 1 ===")

    result(close(frame["site"]["width"], 0.46),
           "Site width = 0.46 um")
    result(close(frame["site"]["height"], 2.72),
           "Site height = 2.72 um")

    # Boundary height and origin.
    result(
        close(frame["boundary"]["y"][0], 0.0)
        and close(frame["boundary"]["y"][1], 2.72),
        "Boundary y = 0.00 to 2.72 um",
    )

    expected_plan_bands = {
        "VGND rail": ("rails", "VGND", "met1", -0.24, 0.24),
        "nsdm": ("nsdm", None, None, -0.19, 1.015),
        "npc": ("npc_band", None, None, 0.975, 1.345),
        "hvtp": ("hvtp", None, None, 1.25, 2.72),
        "nwell": ("nwell", None, None, 1.305, 2.91),
        "psdm": ("psdm", None, None, 1.355, 2.91),
    }

    for label, (key, subkey, layerkey, ymin, ymax) in expected_plan_bands.items():
        obj = frame[key]
        if subkey:
            obj = obj[subkey][layerkey]
        actual = obj["y"]
        result(
            close(actual[0], ymin) and close(actual[1], ymax),
            f"Plan {label} y = {actual[0]} to {actual[1]} um; "
            f"expected {ymin} to {ymax} um",
        )

    vpwr_y = frame["rails"]["VPWR"]["met1"]["y"]
    result(
        close(vpwr_y[0], 2.48) and close(vpwr_y[1], 2.96),
        f"Plan VPWR rail y = {vpwr_y[0]} to {vpwr_y[1]} um; "
        "expected 2.48 to 2.96 um",
    )

    print("\n=== 2. Installed GDS vs Table 1 ===")

    for short in ("inv_1", "nand2_1"):
        name = PREFIX + short
        cell = layout.cell(name)

        if cell is None:
            result(False, f"{name} exists in installed GDS")
            continue

        print(f"\n{short} ({name})")

        # Check the actual prBoundary.
        boundary_layer = layout.find_layer(236, 0)
        boundary_boxes = shape_boxes(cell, boundary_layer, dbu)
        width = frame["site"]["width"] * 3  # expected reference width
        result(
            any(
                close(b[0], 0.0) and close(b[1], 0.0)
                and close(b[2] - b[0], width)
                and close(b[3] - b[1], 2.72)
                for b in boundary_boxes
            ),
            "prBoundary is 3 sites wide (1.38 um) and 2.72 um tall",
        )

        # Check each layer's actual geometry.
        for label, (gds_layer, ymin, ymax) in TABLE1.items():
            layer_index = layout.find_layer(*gds_layer)
            boxes = shape_boxes(cell, layer_index, dbu)

            if label in ("VGND rail", "VPWR rail"):
                # met1/20 contains both rails; test each expected band
                # independently because both share the same GDS layer.
                ok = has_y_band(boxes, ymin, ymax)
            else:
                # Check that the layer's total vertical extent matches.
                ok = bool(boxes) and close(
                    min(b[1] for b in boxes), ymin
                ) and close(
                    max(b[3] for b in boxes), ymax
                )

            result(ok, f"{label} ({gds_layer[0]}/{gds_layer[1]}) "
                       f"has expected y extent {ymin} to {ymax} um")

    print(f"\n=== Summary: {passed} PASS, {failed} FAIL ===")
    if failed:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
