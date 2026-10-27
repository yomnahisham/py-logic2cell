"""Broken case: nand2_1 with hvtp removed. layer_check.py must FAIL on it."""
import klayout.db as db
layout = db.Layout()
layout.read("build/ref/nand2_1.gds")
idx = layout.find_layer(78, 44)
for cell in layout.each_cell():
    cell.shapes(idx).clear()
layout.write("build/ref/broken_no_hvtp.gds")
