"""Deliberately broken Member 2 check: nand2 must not be reported as new."""

from src.hd.redundancy import classify


result = classify(0x8888)
if result[0] == "new":
    raise SystemExit("broken check caught: nand2 was classified as new")
raise SystemExit("broken case intentionally fails when the checker is correct")
