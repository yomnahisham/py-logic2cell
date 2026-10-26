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


def npn_canonical_truth_table(table: int, support_size: int) -> int:
    """Return the smallest table under input and output polarity changes."""

    width = 1 << support_size
    full_mask = (1 << width) - 1
    variants = []
    for input_mask in range(width):
        variant = table
        for input_index in range(support_size):
            if input_mask & (1 << input_index):
                variant = _invert_input(variant, input_index, support_size)
        variants.extend((variant, variant ^ full_mask))
    return min(
        permute_truth_table(variant, permutation)
        for variant in variants
        for permutation in permutations(range(support_size))
    )


def npn_class_count(support_size: int) -> int:
    """Count NPN classes by removing each transformation orbit once."""

    unseen = set(range(1 << (1 << support_size)))
    count = 0
    while unseen:
        representative = next(iter(unseen))
        count += 1
        orbit = set()
        for input_mask in range(1 << support_size):
            variant = representative
            for input_index in range(support_size):
                if input_mask & (1 << input_index):
                    variant = _invert_input(variant, input_index, support_size)
            for output_variant in (variant, variant ^ ((1 << (1 << support_size)) - 1)):
                for permutation in permutations(range(support_size)):
                    orbit.add(permute_truth_table(output_variant, permutation))
        unseen.difference_update(orbit)
    return count


def _invert_input(table: int, input_index: int, support_size: int) -> int:
    result = 0
    for assignment in range(1 << support_size):
        if (table >> (assignment ^ (1 << input_index))) & 1:
            result |= 1 << assignment
    return result


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


def class_rows(cells: list[Cell]) -> list[ClassRow]:
    """Build deterministic rows for the HD class table.

    Single-stage transistor topology is intentionally left as ``unknown`` until
    the project defines and implements the CMOS topology test.
    """

    rows = [
        ClassRow(
            cell=cell.name,
            inputs=" ".join(cell.inputs),
            truth_table=f"0x{cell.truth_table:x}",
            p_class_id=p_class_id(cell.truth_table, len(cell.support)),
            support_size=len(cell.support),
            single_stage="unknown",
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
