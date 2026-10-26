"""Table 4 enumeration and redundancy self-test helpers."""

from __future__ import annotations

from collections import Counter
import os
from pathlib import Path

from .classes import canonical_truth_table, npn_class_count
from .liberty import Cell, parse_liberty_file
from .redundancy import Classification, _classify


def depends_on_all_four_inputs(table: int) -> bool:
    return all(
        any(
            ((table >> assignment) & 1)
            != ((table >> (assignment ^ (1 << input_index))) & 1)
            for assignment in range(16)
            if not (assignment & (1 << input_index))
        )
        for input_index in range(4)
    )


def full_support_p_classes() -> list[int]:
    classes = {
        canonical_truth_table(table, 4)
        for table in range(1 << 16)
        if depends_on_all_four_inputs(table)
    }
    return sorted(classes)


def classify_full_support(cells: tuple[Cell, ...]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for table in full_support_p_classes():
        classification: Classification = _classify(table, cells)
        counts[classification[0]] += 1
    return counts


def run_full_selftest(path: str | os.PathLike[str]) -> Counter[str]:
    """Parse the configured library and classify all full-support P-classes."""

    cells = tuple(parse_liberty_file(str(path)))
    return classify_full_support(cells)


def write_selftest_report(
    library_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
) -> Counter[str]:
    """Write observed redundancy counts without embedding expected values."""

    counts = run_full_selftest(library_path)
    cells = tuple(parse_liberty_file(str(library_path)))
    hd_cells_checked = 0
    hd_cells_exists = 0
    for cell in cells:
        if len(cell.support) <= 4:
            hd_cells_checked += 1
            expanded = _expand_for_selftest(cell.truth_table, len(cell.support))
            if _classify(expanded, cells)[0] == "exists":
                hd_cells_exists += 1
    npn_count = npn_class_count(4)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    total = sum(counts.values())
    with output.open("w", encoding="utf-8") as file:
        file.write(f"library={library_path}\n")
        file.write(f"full_support_p_classes={total}\n")
        file.write(f"hd_cells_checked={hd_cells_checked}\n")
        file.write(f"hd_cells_exists={hd_cells_exists}\n")
        file.write(f"npn_4_input_classes={npn_count}\n")
        for name in ("exists", "exists_inv", "contained", "new"):
            file.write(f"{name}={counts[name]}\n")
    return counts


def _expand_for_selftest(table: int, support_size: int) -> int:
    expanded = 0
    for assignment in range(16):
        source = sum(
            ((assignment >> index) & 1) << index
            for index in range(support_size)
        )
        if (table >> source) & 1:
            expanded |= 1 << assignment
    return expanded
