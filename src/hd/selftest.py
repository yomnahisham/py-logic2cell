"""Table 4 enumeration and redundancy self-test helpers."""

from __future__ import annotations

from collections import Counter
import os
from pathlib import Path

from .classes import canonical_truth_table
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
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    total = sum(counts.values())
    with output.open("w", encoding="utf-8") as file:
        file.write(f"library={library_path}\n")
        file.write(f"full_support_p_classes={total}\n")
        for name in ("exists", "exists_inv", "contained", "new"):
            file.write(f"{name}={counts[name]}\n")
    return counts
