# DD2 Project 1: the targets the overview requires (section 5.1).
# Fill in every target; the placeholders fail until you do.

PDK_ROOT ?= $(HOME)/.ciel
GIVEN    ?= ../DD2_Project1_student_pack/given
IN       ?=

.PHONY: setup check test all demo clean

PDK      ?= $(firstword $(wildcard $(PDK_ROOT)/sky130A $(PDK_ROOT)/ciel/sky130/versions/*/sky130A))
PY       := .venv/bin/python
export HD_LIB_FULL ?= pdk/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib

setup:            ## environment, and links to the PDK and the given files
	@test -n "$(PDK)" || (echo "no sky130A under $(PDK_ROOT), pass PDK=<path>" && exit 1)
	ln -sfn $(PDK) pdk
	ln -sfn $(GIVEN) given
	test -d .venv || python3 -m venv .venv
	$(PY) -m pip install -q -r requirements.txt

check:            ## tool versions, PDK, and the ngspice stress test for Option 1
	@test -d pdk || (echo "pdk link missing: run make setup" && exit 1)
	@test -f given/hd_reduced.lib || (echo "given files missing: run make setup" && exit 1)
	yosys -V
	iverilog -V 2>/dev/null | head -1
	python3 --version
	docker run --rm dd2-layout-tools magic --version
	docker run --rm dd2-layout-tools netgen -batch quit
	docker run --rm dd2-layout-tools /opt/dd2/stress_test/check_stress.sh
	@echo "check: OK"

test:             ## every test, including the broken cases in tests/broken/
	$(PY) -m pytest -q tests
	$(PY) src/frame_check.py

all:              ## the whole flow
	for r in requests/hd/*.json; do $(PY) -m src.cell.build $$r --hd $$(basename $$r .json) || exit 1; done

demo:             ## what the interview runs: make demo IN=<request or design>
	@test -n "$(IN)" || (echo "usage: make demo IN=<request or design>" && exit 1)
	$(PY) -m src.cell.build $(IN)

clean:
	rm -rf build
