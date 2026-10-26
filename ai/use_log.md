# AI use log (overview, Appendix B)

| ID | Date | Who | Tool and model | What you asked | What you kept or changed | How you checked it | Commit |
|---|---|---|---|---|---|---|---|
| M2-001 | 2026-10-26 | Member 2 | Copilot SDK in VS Code | Implement the Step 1 Liberty parser and Boolean function evaluator | Added `src/hd/liberty.py`, parser tests, and package initialization | 11 local pytest tests; full PDK validation returned 324 eligible cells from the 428-cell library | — |
| M2-002 | 2026-10-27 | Member 2 | Copilot | Implement redundancy classification against the full HD library | Added `src/hd/redundancy.py` and focused tests for exists, exists_inv, contained, and new | 19 local pytest tests; full PDK smoke test classified expanded AND as exists and an unmatched function as new | — |
