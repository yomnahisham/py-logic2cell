"""Enumerate cuts of up to k inputs in an AIG, with a truth table for each cut.

Truth tables are built while the cuts are merged: a node's table is the AND of its
two fanin cut tables, each widened to the merged leaves and inverted where the edge
is. The check simulates each cut's logic again, node by node from the root down to
the leaves, for every input combination, which is an independent second way to get
the same table.

Bit i of a cut table is the root's value when leaf j of the (sorted) cut equals bit j of i.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.aig import aiger


def widen(table, leaves, to):
    """A table over `leaves` as a table over the larger leaf tuple `to`."""
    where = [to.index(leaf) for leaf in leaves]
    out = 0
    for i in range(1 << len(to)):
        j = sum(((i >> w) & 1) << pos for pos, w in enumerate(where))
        if table >> j & 1:
            out |= 1 << i
    return out


class CutEnumerator:
    def __init__(self, aiger_path):
        self.path = aiger_path
        aig = aiger.read(aiger_path)
        self.inputs = [lit // 2 for lit in aig.inputs]
        self.latches = [lat[0] // 2 for lat in aig.latches]
        self.outputs = aig.outputs
        self.ands = {}  # node -> (l_var, l_inv, r_var, r_inv)
        for lhs, rhs0, rhs1 in aig.ands:
            self.ands[lhs // 2] = (rhs0 // 2, rhs0 % 2, rhs1 // 2, rhs1 % 2)

    def enumerate_cuts(self, k=4):
        """node -> {cut (sorted leaf tuple): truth table}."""
        node_cuts = {0: {(): 0}}  # constant false: no leaves
        for v in self.inputs + self.latches:
            node_cuts[v] = {(v,): 0b10}
        # AIGER lists AND gates in topological order
        for n, (l_v, l_inv, r_v, r_inv) in self.ands.items():
            merged = {(n,): 0b10}
            for c1, t1 in node_cuts[l_v].items():
                for c2, t2 in node_cuts[r_v].items():
                    union = tuple(sorted(set(c1) | set(c2)))
                    if len(union) > k or union in merged:
                        continue
                    full = (1 << (1 << len(union))) - 1
                    a = widen(t1, c1, union) ^ (full if l_inv else 0)
                    b = widen(t2, c2, union) ^ (full if r_inv else 0)
                    merged[union] = a & b
            node_cuts[n] = self.drop_dominated(merged)
        return node_cuts

    @staticmethod
    def drop_dominated(cuts):
        """Remove cuts that contain a smaller cut of the same node. Such a cut lists a node
        together with the leaves it is made from, so its leaves are not independent."""
        sets = {c: set(c) for c in cuts}
        return {c: t for c, t in cuts.items()
                if not any(o != c and sets[o] < sets[c] for o in cuts)}

    def evaluate_subgraph(self, root, leaves, input_assignment):
        """Simulates logic recursively from root down to leaves for given input assignment."""
        leaf_map = dict(zip(leaves, input_assignment))

        def eval_node(v):
            if v in leaf_map:
                return leaf_map[v]
            if v == 0:
                return 0
            if v not in self.ands:
                raise ValueError(f"node {v} is outside the cut {leaves} of {root}")
            l_v, l_inv, r_v, r_inv = self.ands[v]
            return (eval_node(l_v) ^ l_inv) & (eval_node(r_v) ^ r_inv)

        return eval_node(root)

    def compute_truth_table(self, root, leaves):
        """Truth table of a cut by simulation."""
        tt = 0
        for idx in range(1 << len(leaves)):
            bits = [(idx >> i) & 1 for i in range(len(leaves))]
            tt |= self.evaluate_subgraph(root, leaves, bits) << idx
        return tt

    def verify_cut(self, root, leaves, truth_table):
        """Brute-force check: the given table against simulation, bit by bit."""
        return self.compute_truth_table(root, leaves) == truth_table

    def check(self, node_cuts):
        """Every cut's table against simulation. Returns the cuts that disagree."""
        return [(n, c) for n, cuts in node_cuts.items() if n in self.ands
                for c, t in cuts.items() if not self.verify_cut(n, c, t)]
