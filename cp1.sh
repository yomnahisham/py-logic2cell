#!/bin/bash
set -euo pipefail

echo "=================================================="
echo "          DD2 PROJECT CP1 FULL SUITE              "
echo "=================================================="

# 1. Area Mapping (Table 1)
echo -e "\n[1/4] Reproducing Table 1 Area Statistics..."
bash src/table1/table1.sh

# 2. AIG Export & Cut Enumeration
echo -e "\n[2/4] Generating AIG Files and Cut Enumeration Tests..."
bash src/aig/all_aigs.sh
python3 src/cut_enum/test_cut_verifier.py

# 3...

echo -e "\n=================================================="
echo "          CP1 EXECUTION COMPLETE                  "
echo "=================================================="