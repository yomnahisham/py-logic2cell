"""P-class canonicalization and HD class-table generation."""

from __future__ import annotations

from dataclasses import dataclass
import csv
from itertools import permutations
from pathlib import Path

from .liberty import Cell


def permute_truth_table(table: int, permutation: tuple[int, ...]) -> int:
    """Return ``table`` with output variable positions permuted."""

    width = 1 << len(permutation)
    result = 0
    for new_assignment in range(width):
        old_assignment = sum(
            ((new_assignment >> new_index) & 1) << old_index
            for new_index, old_index in enumerate(permutation)
        )
        if (table >> old_assignment) & 1:
            result |= 1 << new_assignment
    return result


def canonical_truth_table(table: int, support_size: int) -> int:
    """Return the smallest truth table under input permutations."""

    if support_size < 0:
        raise ValueError("support size cannot be negative")
    if table < 0 or table >= (1 << (1 << support_size)):
        raise ValueError("truth table does not fit its support size")
    permutations_to_check = permutations(range(support_size))
    return min(
        permute_truth_table(table, permutation)
        for permutation in permutations_to_check
    )


def p_class_id(table: int, support_size: int) -> str:
    """Return a stable printable P-class identifier."""

    canonical = canonical_truth_table(table, support_size)
    digits = max(1, (1 << support_size) // 4)
    return f"p{support_size}_{canonical:0{digits}x}"


@dataclass(frozen=True)
class ClassRow:
    cell: str
    inputs: str
    truth_table: str
    p_class_id: str
    support_size: int
    single_stage: str


def _single_stage(cell: Cell) -> str:
    from src.common.stage import single_stage
    if len(cell.support) > 4:
        return "n/a"
    return "yes" if single_stage(cell.truth_table, len(cell.support)) else "no"


def class_rows(cells: list[Cell]) -> list[ClassRow]:
    """Build deterministic rows for the HD class table.

    single_stage is yes when one static CMOS stage with at most 3 transistors in
    series computes the cell's function, n/a for cells with more than 4 inputs.
    """

    rows = [
        ClassRow(
            cell=cell.name,
            inputs=" ".join(cell.inputs),
            truth_table=f"0x{cell.truth_table:x}",
            p_class_id=p_class_id(cell.truth_table, len(cell.support)),
            support_size=len(cell.support),
            single_stage=_single_stage(cell),
        )
        for cell in cells
    ]
    return sorted(rows, key=lambda row: row.cell)


def write_class_table(cells: list[Cell], path: str | Path) -> None:
    """Write the HD class table as deterministic CSV."""

    rows = class_rows(cells)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            ["cell", "inputs", "truth_table", "p_class_id", "support_size", "single_stage"]
        )
        writer.writerows(
            (
                row.cell,
                row.inputs,
                row.truth_table,
                row.p_class_id,
                row.support_size,
                row.single_stage,
            )
            for row in rows
        )


if __name__ == "__main__":
    import os
    from .liberty import parse_liberty_file
    write_class_table(parse_liberty_file(os.environ["HD_LIB_FULL"]), "results/hd/hd_classes.csv")
