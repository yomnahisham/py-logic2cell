import json
from pathlib import Path

import pytest

from src.common.request import RequestError, read_request, truth_table, write_response

ROOT = Path(__file__).resolve().parents[2]
BROKEN = sorted((ROOT / "tests/broken/requests").glob("*.json"))
UNSUPPORTED = {"five_inputs", "two_outputs"}


def test_example_request():
    request = read_request(ROOT / "docs/interface/request_example.json")
    assert request.truth_table == 0x077F
    assert request.inputs == ("A", "B", "C", "D")


@pytest.mark.parametrize(("expression", "inputs", "table"), [
    ("!A", ("A",), 0x1),
    ("!(A & B)", ("A", "B"), 0x7),
    ("A & !B", ("A", "B"), 0x2),
    ("A & !B", ("B", "A"), 0x4),
    ("A ^ B", ("A", "B"), 0x6),
    ("!((A & B) | C)", ("A", "B", "C"), 0x07),
    ("B", ("A", "B", "C"), 0xCC),
])
def test_truth_table(expression, inputs, table):
    assert truth_table(expression, inputs) == table


@pytest.mark.parametrize("path", BROKEN, ids=[p.stem for p in BROKEN])
def test_broken_request_is_refused(path):
    with pytest.raises(RequestError) as error:
        read_request(path)
    assert error.value.status == ("unsupported" if path.stem in UNSUPPORTED else "fail")


def test_response_matches_example(tmp_path):
    example = json.loads((ROOT / "docs/interface/response_example.json").read_text())
    rest = {k: v for k, v in example.items() if k not in ("request_id", "status", "reason")}
    write_response(tmp_path / "r.json", "B-017", "pass", **rest)
    assert (tmp_path / "r.json").read_text() == json.dumps(example, indent=2) + "\n"


def test_fail_needs_reason(tmp_path):
    with pytest.raises(ValueError):
        write_response(tmp_path / "r.json", "B-017", "fail")
