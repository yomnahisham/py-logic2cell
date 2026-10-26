# DD2 Project 1: the targets the overview requires (section 5.1).
# Fill in every target; the placeholders fail until you do.

PDK_ROOT ?= $(HOME)/.ciel
GIVEN    ?= ../DD2_Project1_student_pack/given
IN       ?=

.PHONY: setup check test all demo clean

setup:            ## environment, and links to the PDK and the given files
	ln -sfn $(PDK_ROOT)/sky130A pdk
	ln -sfn $(GIVEN) given
	@echo "add your own setup steps here"

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
	@echo "not written yet" && exit 1

all:              ## the whole flow
	@echo "not written yet" && exit 1

demo:             ## what the interview runs: make demo IN=<request or design>
	@test -n "$(IN)" || (echo "usage: make demo IN=<request or design>" && exit 1)
	@echo "not written yet" && exit 1

clean:
	rm -rf build
