.PHONY: m2-check m2-all

m2-check:
	@test -n "$(HD_LIB_FULL)" || (echo "HD_LIB_FULL is required" && exit 1)
	python3 -m unittest tests.m2.test_classes tests.m2.test_liberty tests.m2.test_redundancy
	@if PYTHONPATH=. python3 tests/broken/m2_redundancy_must_not_be_new.py; then echo "broken case unexpectedly passed"; exit 1; else echo "broken case caught"; fi

m2-all:
	@test -n "$(HD_LIB_FULL)" || (echo "HD_LIB_FULL is required" && exit 1)
	PYTHONPATH=. python3 -c 'import os; from src.hd.selftest import write_selftest_report; write_selftest_report(os.environ["HD_LIB_FULL"], "results/hd/redundancy_selftest.txt")'
