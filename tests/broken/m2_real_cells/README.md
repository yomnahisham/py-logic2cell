Broken cases for the real-cell intake (src/hd/real_cells.py). Each folder stands in for cells/:
- wrong_function: a passing response whose Liberty function is the majority, not its complement
  (the request is 0x077F, !((C&D) | (A&B&(C|D)))). The intake must refuse it.
- not_pass: a response with status fail. Appendix A: it must not be used in a mapping.
