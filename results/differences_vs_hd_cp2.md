# Our cells against the installed HD cells: what differs, and what it costs

Option 1 handout, section 4.1 (Table 4) and section 8.3 ("Comparison with HD: every difference between your
reference cells and the installed ones, and which of them cost area or delay"). DRAFT for the report: every
number below is copied from the file named next to it; nothing here is measured by hand.

Sources:
- layout comparison of each reference cell: `cells/dd2_gc1__<cell>/report.json` (key `compare`), and for
  o31ai_1 `results/compare_o31ai_1_vs_hd.json` (both written by `src/cell/compare.py`)
- width and area of every Table 6 cell: `results/table6_vs_hd.csv`
- timing, both cells characterized by our own flow (Table 4 asks for this): `results/timing_vs_hd.txt`,
  `results/timing_vs_hd.csv`, and for o31ai_1 `results/timing_vs_hd_o31ai.txt` / `.csv`. "At the point" means
  the HD table entry nearest 100 ps and 10 fF (section 6)
- transistor connections: `cells/dd2_gc1__<cell>/cell.spice` and the PDK's `sky130_fd_sc_hd.spice`
- characterizer accuracy: `results/char_validation*.txt`; design level: `results/spm_design_level.txt`

## 1. Summary

| Cell | Sites ours / HD | Transistors (LVS vs HD) | Y capacitance ours / HD (fF) | Slowest arc at the point, ours vs HD | Input capacitance, ours vs HD |
|---|---|---|---|---|---|
| inv_1 | 3 / 3 | match | 0.3508 / 0.3519 | +0.1% | -0.3% |
| nand2_1 | 3 / 3 | match | 0.4933 / 0.4293 | +0.2% | -1.1 to -0.3% |
| nor2_1 | 3 / 3 | match | 0.4487 / 0.3889 | +1.8% | -1.9 to -1.3% |
| nand3_1 | 5 / 4 | match | 0.6124 / 0.7796 | -0.7% | -3.4 to -0.2% |
| a21oi_1 | 5 / 4 | match | 0.562 / 0.4142 | +2.9% | -5.6 to -2.1% |
| o21ai_1 | 5 / 4 | match | 0.553 / 0.3984 | +8.5% | -9.5 to -1.2% |
| o31ai_1 (our choice) | 6 / 6 | match | 0.5997 / 0.4842 | +2.0% | -10.3 to -4.1% |

Every one of them has the HD frame (Table 4 "Frame": match, and an XOR of zero on every frame layer where the
widths are equal: inv_1, nand2_1, nor2_1, o31ai_1), the HD transistors including every W and L, li1 wiring
inside with met1 only on the rails, and passes abutment with zero DRC errors.

**In one sentence:** where our cell is as wide as HD's, its slowest arc is within 2% of HD's; where it is one
site wider, the extra site costs area always and delay only when it lengthens the output wire.

## 2. Table 4, row by row

**Frame (must match): matches.** Boundary, rails, nwell, nsdm, psdm and hvtp have the y extents of Table 1 in
all seven cells; where the widths are equal the XOR of those layers is 0.0 um2.

**Transistors (must match, including every W and L): match** for all six reference cells and for o31ai_1.

**Pins (must match: inputs on li1 in the npc band, supplies on the rails): ours match.** All our input pins are
li1 squares in the npc band. SkyWater's own cells do not always follow this: some HD input pins sit in a row
band instead (a21oi_1 B1; o21ai_1 A2 and B1; o31ai_1 A2; and among the multi-stage cells a21o_1 A1 and mux2_1 S
and A1).

**Wiring layers (must match: li1 inside, met1 only for the rails): match** for the six reference cells,
o31ai_1 and a21o_1. mux2_1 is the exception: ours uses met1 inside the cell, HD's does not.

**Abutment (must pass DRC): passes**, 0 errors, for every cell (`checks.abutment` in each `response.json`).

**Width (report and explain each extra site):**

| Cell | Ours / HD | Where the extra site comes from (gate x positions and pitches in `report.json`) |
|---|---|---|
| nand3_1 | 5 / 4 | Same gate order (C, B, A) and the same pitches (0.42, 0.48 um) as HD; our first gate sits at x = 0.785 um against HD's 0.47 um. The extra site is margin on the left. |
| a21oi_1 | 5 / 4 | Our first gate pitch is 0.66 um against HD's 0.43 um (second pitch 0.48 against 0.445). |
| o21ai_1 | 5 / 4 | Our first gate pitch is 0.66 um against HD's 0.48 um (NMOS row); HD also jogs its PMOS gates (PMOS pitches 0.36 and 0.54 um). |
| nor3_1, o22ai_1, maj3_1 | +1 site each | From `table6_vs_hd.csv`; these test cells have no layout comparison in a report yet. |
| a21o_1 | 7 / 6 | Two stages; the pitch at the stage boundary is 1.06 um against HD's 0.94, and ours breaks the diffusion in both rows (HD: PMOS row only). |
| mux2_1 | 10 / 9 | Three stages; one diffusion break in each row against none in HD, and met1 inside. |
| xor2_1 | 11 / 7 | Three stages; 2 diffusion breaks against HD's 1, and met1 inside (`table6_vs_hd.csv`). The largest gap in Table 6. |

Not yet explained: why our generator chose 0.66 um for the first pitch of a21oi_1 and o21ai_1 when its
own minimum gate pitch is 0.42 um (`results/design_rules.csv`). It is most likely where the poly contacts
of those gates could be placed in the npc band, but this has not been checked.

**Gate order (report and explain each difference):**

| Cell | Ours | HD |
|---|---|---|
| inv_1, nand2_1, nand3_1, o31ai_1 | same as HD | |
| nor2_1 | A, B | B, A (mirror) |
| a21oi_1 | B1, A2, A1 | B1, A1, A2 (A1 and A2 swapped) |
| o21ai_1 | B1, A1, A2 | A1, A2, B1 |

o31ai_1 has the same gate order along the row as HD's but a different orientation of its PMOS stack, see
section 3.

**Parasitics (report):** see the Y column of the summary. Our output wire carries more capacitance than HD's
in nand2_1 (+0.064 fF), nor2_1 (+0.060), a21oi_1 (+0.148), o21ai_1 (+0.155) and o31ai_1 (+0.116), and less in
nand3_1 (-0.167); inv_1 is equal. The wiring capacitance on the input nets differs pin by pin (HD's is larger
on most pins, ours on a21oi_1 A2 and o21ai_1 A1 and B1), but the measured input capacitance is lower than
HD's on every pin of every cell (summary, last column).

**Timing (report):** see the summary and section 3.

## 3. What the differences cost

**Area.** Each extra site is 1.2512 um2 (one site of 0.46 um by 2.72 um: `table6_vs_hd.csv` areas). Of the 14
Table 6 cells that have an HD counterpart, five are as wide as HD's (nand2_1, nor2_1, a22oi_1, and2_1,
o31ai_1), eight are one site wider, and xor2_1 is four wider.

**Delay, cell by cell** (both cells characterized by our flow, so the characterizer's own error cancels):

- **inv_1, nand2_1: none.** Within 0.8% at the point (largest anywhere on the grid: 0.6% for inv_1, 2.1% for
  nand2_1). Same width and gate order. nand2_1's extra 0.064 fF on Y is under 1% of the 9 fF load at the point.
- **nor2_1: rise +1.6 to +2.4%, fall under 1%.** Same width, mirrored gate order, +0.060 fF on Y. The rise goes
  through two high-Vt PMOS in series, the weakest path in the cell, so that is where the extra capacitance
  shows. HD also places its PMOS gates closer (pitch 0.36 against our 0.42 um).
- **nand3_1: about 1% faster, at one more site.** Same gate order and pitches as HD; our Y has less capacitance
  (0.612 against 0.780 fF). The extra site costs area and no delay.
- **a21oi_1: up to +5.6% (transition), slowest arc +2.9%.** The 0.66 um first pitch lengthens the output wire:
  +0.148 fF on Y (+36%). The swapped A1 and A2 put each at a different place in the stack, so the per-pin
  changes differ.
- **o21ai_1: the largest, slowest arc +8.5%, A2 fall transition +13.9%.** Different gate order and +0.155 fF
  on Y (+39%); every rise, which goes through the high-Vt PMOS pull-up, is slower: delay +3.8 to +8.5%,
  transition +7.5 to +9.5%. HD bends A2's
  poly (PMOS and NMOS gates at different x) and routes more li on that pin, so our A2 has 9.5% less input
  capacitance.
- **o31ai_1: per-pin swings of -12% to +14%, slowest arc +2.0%.** Same width, same gate order, same transistors,
  but the PMOS stack is turned around: ours is Y - A1 - A2 - A3 - VPWR, HD's is VPWR - A1 - A2 - A3 - Y
  (`cell.spice` against the PDK netlist). The input whose PMOS is next to Y switches fastest, because the
  internal stack nodes do not have to be charged or discharged with Y. So HD's fastest A pin is A3 and ours is
  A1: our A1 rise is 12.3% faster and our A3 rise 14.4% slower than HD's; the fall changes the same way
  (A1 -7.7%, A3 +12.8%). B1, a single PMOS outside the stack, is within 1%.

**Which differences cost delay:** a longer output wire (a21oi_1, o21ai_1, nor2_1, o31ai_1) and the orientation
of a series stack (o31ai_1). **Which cost area only:** the left margin of nand3_1. **Which cost both:** the wider
first pitch of a21oi_1 and o21ai_1. **What HD does that we do not:** bending a gate's poly so that its PMOS and
NMOS sit at different x (o21ai_1, nor2_1, o31ai_1 B1), which packs the gates closer; and placing the last input
of a stack next to the output.

## 4. The characterizer and the design level (Table 5)

- Against the shipped HD Liberty, on SkyWater's own layouts: median error 3.40% over 2744 entries, every input
  capacitance within 10% (largest +5.3%) (`char_validation.txt`). The error is largest at the smallest load
  (0.5 fF) and always slow there; leaving that column out, the median is 2.81% (computed from
  `char_validation_entries.csv`). It behaves like a little more capacitance on Y in our extraction than in
  SkyWater's characterization; not explained.
- With the stock ngspice the median is 5.26% (`char_validation_stock.txt`); with tables indexed by the full ramp
  it is 7.42% (`char_validation_fullramp.txt`); both fail, as they should.
- Tutorial 4's SPM, mapped and timed with HD and with HD carrying our six characterized cells: ABC picks the same
  netlist, and the worst path moves from 0.7727 to 0.7734 ns, +0.7 ps (+0.09%) (`spm_design_level.txt`). None of
  our cells is on that path; the change comes from the input capacitance our cells put on it.

## 5. What none of our checks covers

- **LVS against HD says "match" for o31ai_1, yet the two cells time differently.** Netgen treats the order of
  series transistors as interchangeable, so a reversed stack is invisible to it. Only the timing comparison
  found it.
- **Magic could not extract the resistance of one net in some SkyWater layouts** (a22oi_1 Y, a31oi_1 A1,
  o211ai_1 A2, a211oi_1 A1): Magic rounds pin boxes to 0.01 um and pushed a corner off the li. `compare.py`
  now rounds HD pin boxes inward in our copy; this changed the signal-net resistance of the cells that already
  extracted by under 1 ohm and their timing by at most 0.064% (AI log A-002).
- No multi-stage cell has been characterized yet: SA/SB matching finds a transistor's gate by its input label,
  which the internal gates of a multi-stage cell do not have, so a21o_1, mux2_1, and2_1, maj3_1 and xor2_1 have
  no timing comparison (not tried; expected to need a change to `stress.py`).

## 6. Open questions (not checked)

1. Why the generator uses a 0.66 um first pitch in a21oi_1 and o21ai_1.
2. Whether the slow-at-small-load error of the characterizer comes from SkyWater characterizing with less
   parasitic capacitance, or from our extraction counting the drain junction twice.
3. Whether orienting each series stack with its last input next to the output, as HD does, would be the
   better default for the generator.
