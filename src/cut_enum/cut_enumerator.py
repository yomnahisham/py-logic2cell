import sys

class CutEnumerator:
    def __init__(self, aiger_path):
        self.path = aiger_path
        self.inputs = []
        self.outputs = []
        self.ands = {} # node -> (l_var, l_inv, r_var, r_inv)
        self.parse_aiger()

    def parse_aiger(self):
        with open(self.path, 'r') as f:
            header = f.readline().strip().split()
            if header[0] != 'aag':
                raise ValueError("Currently parses ASCII .aag format (run aiger2aag if binary)")
            M, I, L, O, A = map(int, header[1:6])
            
            for _ in range(I):
                self.inputs.append(int(f.readline().strip()) // 2)
            for _ in range(L):
                f.readline() # Skip latches
            for _ in range(O):
                self.outputs.append(int(f.readline().strip()))
            for _ in range(A):
                parts = list(map(int, f.readline().strip().split()))
                out_var = parts[0] // 2
                l_var, l_inv = parts[1] // 2, parts[1] % 2
                r_var, r_inv = parts[2] // 2, parts[2] % 2
                self.ands[out_var] = (l_var, l_inv, r_var, r_inv)

    def enumerate_cuts(self, k=4):
        node_cuts = {}
        # Primary inputs have single-element cuts
        for inp in self.inputs:
            node_cuts[inp] = { (inp,) }
        
        # Topological order for AND gates
        for n, (l_v, l_inv, r_v, r_inv) in self.ands.items():
            l_cuts = node_cuts.get(l_v, { (l_v,) })
            r_cuts = node_cuts.get(r_v, { (r_v,) })
            
            merged = { (n,) }
            for c1 in l_cuts:
                for c2 in r_cuts:
                    union = tuple(sorted(set(c1 + c2)))
                    if len(union) <= k:
                        merged.add(union)
            node_cuts[n] = merged
        return node_cuts

    def evaluate_subgraph(self, root, leaves, input_assignment):
        """Simulates logic recursively from root down to leaves for given input assignment."""
        leaf_map = dict(zip(leaves, input_assignment))
        
        def eval_node(v):
            if v in leaf_map:
                return leaf_map[v]
            if v == 0:
                return 0
            if v not in self.ands:
                return 0
            l_v, l_inv, r_v, r_inv = self.ands[v]
            val_l = eval_node(l_v) ^ l_inv
            val_r = eval_node(r_v) ^ r_inv
            return val_l & val_r

        return eval_node(root)

    def compute_truth_table(self, root, leaves):
        """Computes full integer truth table for a cut of size <= 4."""
        k = len(leaves)
        tt = 0
        for idx in range(1 << k):
            bits = [(idx >> i) & 1 for i in range(k)]
            res = self.evaluate_subgraph(root, leaves, bits)
            tt |= (res << idx)
        return tt

    def verify_cut(self, root, leaves, truth_table):
        """Brute-force check: compares calculated truth table bit-by-bit against simulated output."""
        k = len(leaves)
        for idx in range(1 << k):
            bits = [(idx >> i) & 1 for i in range(k)]
            simulated = self.evaluate_subgraph(root, leaves, bits)
            expected = (truth_table >> idx) & 1
            if simulated != expected:
                return False
        return True