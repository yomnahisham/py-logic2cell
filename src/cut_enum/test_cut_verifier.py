import sys
from cut_enumerator import CutEnumerator

def test_verifier():
    # Use one of exported raw AIGs
    # Note: convert binary .aig to ascii .aag using yosys/aiger tools if needed
    aig_path = str(__import__("pathlib").Path(__file__).resolve().parents[2] / "build/aigs/cpu8_raw.aag")
    
    print("Testing Cut Enumerator & Brute-Force Checker...")
    enumerator = CutEnumerator(aig_path)
    cuts = enumerator.enumerate_cuts(k=4)
    
    verified_count = 0
    test_node = None
    test_cut = None
    correct_tt = None

    for node, cut_set in cuts.items():
        for cut in cut_set:
            if len(cut) > 1: # non-trivial cut
                tt = enumerator.compute_truth_table(node, cut)
                assert enumerator.verify_cut(node, cut, tt) == True
                verified_count += 1
                if test_node is None:
                    test_node, test_cut, correct_tt = node, cut, tt
    
    print(f"PASS: Successfully verified {verified_count} cuts against AIG logic.")

    # Broken Case Test (Section 9.1 requirement)
    print("\nTesting Broken Case (Intentionally corrupted truth table)...")
    corrupted_tt = correct_tt ^ 0x1  # Flip LSB of truth table
    passed_check = enumerator.verify_cut(test_node, test_cut, corrupted_tt)
    
    if not passed_check:
        print(f"PASS: Checker successfully detected wrong truth table on Node {test_node}!")
    else:
        print("FAIL: Checker failed to catch corrupted truth table!")
        sys.exit(1)

if __name__ == '__main__':
    test_verifier()