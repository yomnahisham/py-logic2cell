"""Diagnostics for the Table 3 contained-class relation."""

from __future__ import annotations

from collections import Counter
from itertools import permutations, product

from .classes import canonical_truth_table
from .liberty import Cell
from .selftest import depends_on_all_four_inputs, full_support_p_classes


def expand(table: int, support_size: int) -> int:
    result = 0
    for assignment in range(16):
        source = sum(
            ((assignment >> index) & 1) << index
            for index in range(support_size)
        )
        if (table >> source) & 1:
            result |= 1 << assignment
    return result


def generated_contained_classes(cells: tuple[Cell, ...]) -> dict[int, str]:
    generated: dict[int, str] = {}
    for cell in cells:
        support_size = len(cell.support)
        if support_size <= 4:
            mappings = product(range(6), repeat=support_size)
            for mapping in mappings:
                table = 0
                for assignment in range(16):
                    source = sum(
                        ((assignment >> destination) & 1) << source_index
                        for source_index, destination in enumerate(mapping)
                        if destination < 4
                        and (assignment >> destination) & 1
                    )
                    source += 0
                    if any(destination == 5 for destination in mapping):
                        source |= sum(
                            1 << source_index
                            for source_index, destination in enumerate(mapping)
                            if destination == 5
                        )
                    if (cell.truth_table >> source) & 1:
                        table |= 1 << assignment
                generated.setdefault(canonical_truth_table(table, 4), cell.name)
        else:
            for selected in permutations(range(support_size), 4):
                remaining = set(range(support_size)) - set(selected)
                for constants in product((0, 1), repeat=len(remaining)):
                    fixed = dict(zip(sorted(remaining), constants))
                    table = 0
                    for assignment in range(16):
                        source = sum(
                            ((assignment >> candidate_index) & 1) << cell_index
                            for candidate_index, cell_index in enumerate(selected)
                        )
                        source |= sum(
                            value << cell_index for cell_index, value in fixed.items()
                        )
                        if (cell.truth_table >> source) & 1:
                            table |= 1 << assignment
                    generated.setdefault(canonical_truth_table(table, 4), cell.name)
    return generated


def summarize(cells: tuple[Cell, ...]) -> dict[str, object]:
    expected = set(full_support_p_classes())
    generated = generated_contained_classes(cells)
    full_support = {
        key: cell
        for key, cell in generated.items()
        if depends_on_all_four_inputs(key)
    }
    return {
        "expected": len(expected),
        "generated": len(generated),
        "generated_full_support": len(full_support),
        "sample_full_support": list(full_support.items())[:20],
        "support_distribution": Counter(len(cell.support) for cell in cells),
    }
