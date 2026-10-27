# AI mistakes log (overview, Appendix B)

| ID | Log entry | What was wrong | How you caught it | Would a weaker check have missed it? |
|---|---|---|---|---|
| M2-001 | 2026-10-26 | Initial Liberty parser matched only unquoted `direction : input/output` values | Full-library validation returned 0 eligible cells; a diagnostic of `nand2_1` showed quoted directions | Yes; fixture-only tests used unquoted directions and passed |
| J-001 | 2026-10-27 | The generated `map.sh` contained mistakes that took a long time to diagnose | Repeatedly debugging the mapping flow and comparing its output against the expected Table 1 results exposed the errors | Yes; a weaker check could have accepted the script without reproducing Table 1 |
| J-002 | 2026-10-27 | Gemini 3.6 Thinking provided some incorrect `.sh` script syntax | Reviewing the generated shell-script syntax exposed errors, which were fixed before keeping the changes | Yes; a weaker review could have kept invalid shell syntax |
