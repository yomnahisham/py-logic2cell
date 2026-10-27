# AI use log (overview, Appendix B)

| ID | Date | Who | Tool and model | What you asked | What you kept or changed | How you checked it | Commit |
|---|---|---|---|---|---|---|---|
| M2-001 | 2026-10-26 | Member 2 | Copilot SDK in VS Code | Implement the Step 1 Liberty parser and Boolean function evaluator | Added `src/hd/liberty.py`, parser tests, and package initialization | 11 local pytest tests; full PDK validation returned 324 eligible cells from the 428-cell library | — |
| M2-002 | 2026-10-27 | Member 2 | Copilot | Implement redundancy classification against the full HD library | Added `src/hd/redundancy.py` and focused tests for exists, exists_inv, contained, and new | 19 local pytest tests; full PDK smoke test classified expanded AND as exists and an unmatched function as new | — |
| J-001 | 2026-10-27 | Jacques | Gemini 3.6 Thinking | Install all dependencies, reproduce Table 1, and build the Table 1 flow | Installed the project dependencies; modified the given `map.sh` and helped build `scripts/table1.sh` | Reproduced Table 1 with the resulting mapping flow | 527e818 |
| J-002 | 2026-10-27 | Jacques | Gemini 3.6 Thinking | Understand how to write the syntax for the `.sh` script | Used the guidance to write the shell-script syntax and corrected errors in the generated instructions before keeping the changes | Reviewed and corrected the shell script errors | ffc74a2 |
| J-003 | 2026-10-27 | Jacques | Gemini 3.6 Thinking | Implement the cut enumerator and its tester | Added the cut enumerator and its tests | Verified the cut enumerator with its tester | 0dfbf8d |
