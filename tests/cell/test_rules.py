from src.cell import layout, rules


def test_every_number_meets_its_rule():
    assert all(r["ok"] for r in rules.rows())


def test_broken_contact_too_close_to_gate(monkeypatch):
    monkeypatch.setattr(layout, "CUT_GATE", 0.045)
    bad = [r["what"] for r in rules.rows() if not r["ok"]]
    assert "contact to standard cell gate" in bad and "gate pitch over a contacted column" in bad
