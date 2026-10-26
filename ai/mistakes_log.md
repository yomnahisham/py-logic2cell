# AI mistakes log (overview, Appendix B)

| ID | Log entry | What was wrong | How you caught it | Would a weaker check have missed it? |
|---|---|---|---|---|
| M2-001 | 2026-10-26 | Initial Liberty parser matched only unquoted `direction : input/output` values | Full-library validation returned 0 eligible cells; a diagnostic of `nand2_1` showed quoted directions | Yes; fixture-only tests used unquoted directions and passed |
| M2-002 | 2026-10-27 | Initial containment implementation produced 0 instead of the handout's 38 full-support classes | Real-PDK Table 4 self-test returned `exists=24`, `exists_inv=20`, `contained=0`, `new=3860`; support and canonicalization diagnostics ruled out parser/count errors | Yes; the 3,904-class enumeration and fixture tests still passed |
| M2-003 | 2026-10-27 | `m2-check` initially treated a missing `PYTHONPATH` import as a caught broken case | WSL output showed `ModuleNotFoundError: No module named 'src'`; the target was fixed to run the broken script with `PYTHONPATH=.` | Yes; the target appeared to pass while never exercising the checker |
