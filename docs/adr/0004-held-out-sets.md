# ADR 0004: Blind held-out sets, first runs kept

Status: accepted

## Context
The simulated tenders were written by the same author as the engine, so they share its
assumptions. The first held-out set showed how large that gap was (23.6% precision).

## Decision
Held-out bids (and from v2 the BoQs) are written by an agent that reads only
`heldout/WRITING_BIDS.md`. A set is run once; `reports/heldout/<set>/first_run.json` and
`FIRST_RUN.md` are never rewritten (CI checks it). If the failures are studied and the engine is
changed, the set becomes a regression set (`heldout/<set>/STATUS`) and a new blind set is written.

## Consequences
+ The README can quote a number that was not tuned on.
− Each round costs a new set; numbers on small sets (11 bids) are noisy.
