# Our reference cells against the installed HD cells (Table 4)

Written by `python -m src.cell.differences` from `cells/dd2_gc1__<cell>/report.json` (key `compare`) and
`results/timing_vs_hd.csv`; the side-by-side pictures are `cells/dd2_gc1__<cell>/vs_hd.png`. Timing is at
the HD table point nearest 100 ps and 10 fF, both cells characterized by our flow. The version written
by hand at checkpoint 2 is `results/differences_vs_hd_cp2.md`.

| Cell | Frame (XOR um2) | Transistors (LVS vs HD) | Pins, ours / HD | Wiring | Sites ours / HD | Gate order ours / HD (NMOS row) | Gate pitch ours / HD (um) | Y cap ours / HD (fF) | Slowest arc ours / HD (ns) | Input cap vs HD |
|---|---|---|---|---|---|---|---|---|---|---|
| inv_1 | match (0) | match | all in the npc band / all in the npc band | li1 inside, met1 rails only | 3 / 3 | A / A |  /  | 0.3507 / 0.3519 | 0.1231 / 0.1230 (+0.1%) | -0.3 to -0.3% |
| nand2_1 | match (0) | match | all in the npc band / all in the npc band | li1 inside, met1 rails only | 3 / 3 | B A / B A | 0.42 / 0.42 | 0.4933 / 0.4293 | 0.1395 / 0.1392 (+0.2%) | -1.1 to -0.3% |
| nor2_1 | match (0) | match | all in the npc band / all in the npc band | li1 inside, met1 rails only | 3 / 3 | A B / B A | 0.42 / 0.42 | 0.4481 / 0.3889 | 0.1795 / 0.1763 (+1.8%) | -1.9 to -1.3% |
| nand3_1 | match (0) | match | all in the npc band / all in the npc band | li1 inside, met1 rails only | 4 / 4 | A B C / C B A | 0.42, 0.42 / 0.42, 0.48 | 0.6423 / 0.7796 | 0.1529 / 0.1558 (-1.9%) | -4.2 to +0.3% |
| a21oi_1 | match (0) | match | all in the npc band / A1, B1 in a row band | li1 inside, met1 rails only | 4 / 4 | B1 A1 A2 / B1 A1 A2 | 0.42, 0.42 / 0.43, 0.445 | 0.3573 / 0.4142 | 0.2165 / 0.2186 (-0.9%) | -6.6 to -2.7% |
| o21ai_1 | match (widths differ) | match | all in the npc band / A2, B1 in a row band | li1 inside, met1 rails only | 5 / 4 | B1 A2 A1 / A1 A2 B1 | 0.6, 0.42 / 0.48, 0.42 | 0.3933 / 0.3984 | 0.2103 / 0.2053 (+2.4%) | -10.1 to +0.9% |

Every row marked "must match" in Table 4 (frame, transistors, our input pins on li1 in the npc band, li1 wiring with met1 only on the rails, abutment with 0 DRC errors): matches for all six cells.

## Differences to explain

- **nor2_1**: gate order A B against HD's B A.
- **nand3_1**: gate order A B C against HD's C B A.
- **o21ai_1** is 1 site wider. Pins: ours all in the npc band, HD A2, B1 in a row band; NMOS gate pitch ours [0.6, 0.42] against HD's [0.48, 0.42] um.
- **o21ai_1**: gate order B1 A2 A1 against HD's A1 A2 B1.
