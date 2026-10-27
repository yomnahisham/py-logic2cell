#!/usr/bin/env bash
# Rerun every finished check and write its output to results/. Activate the venv first.
set -u
cd "$(dirname "$0")/.."
mkdir -p results
status=0

echo "== environment";  make check 2>&1 | tee results/check.txt
[ "${PIPESTATUS[0]}" -eq 0 ] || status=1

echo "== extraction";   python3 src/extract_cells.py 2>&1 | tee results/extract_cells.txt
[ "${PIPESTATUS[0]}" -eq 0 ] || status=1

echo "== frame check";  python3 src/frame_check.py 2>&1 | tee results/frame_check.txt
[ "${PIPESTATUS[0]}" -eq 0 ] || status=1

echo "== layer check, installed cells"
: > results/layer_check_installed.txt
for c in inv_1 nand2_1 tapvpwrvgnd_1 fill_1; do
  python3 src/layer_check.py build/ref/$c.gds sky130_fd_sc_hd__$c 2>&1 | tee -a results/layer_check_installed.txt
  [ "${PIPESTATUS[0]}" -eq 0 ] || status=1
done

echo "== layer check, broken case (must FAIL)"
python3 tests/broken/make_no_hvtp.py
python3 src/layer_check.py build/ref/broken_no_hvtp.gds sky130_fd_sc_hd__nand2_1 > results/layer_check_broken.txt 2>&1
rc=$?
echo "exit code: $rc" | tee -a results/layer_check_broken.txt
cat results/layer_check_broken.txt
[ "$rc" -eq 1 ] || { echo "BROKEN CASE DID NOT FAIL"; status=1; }

echo "== front end";    python3 tests/test_front_end.py 2>&1 | tee results/front_end_tests.txt
[ "${PIPESTATUS[0]}" -eq 0 ] || status=1

[ "$status" -eq 0 ] && echo "ALL RESULTS WRITTEN, ALL CHECKS AS EXPECTED" || echo "SOMETHING FAILED: read the output above"
exit $status
