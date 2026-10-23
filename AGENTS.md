# Working on this repository

Fast feedback: `pytest -q -m "not slow"` (seconds), `cd platform && npm test` (needs Postgres,
`TEST_DATABASE_URL`), `ble run` (everything, ends with the release gate).

Invariants:
- The engine (`ingest`, `text`, `resolve/match.py`, `deviate`, `graph`, `harness`, `workflows.py`,
  `chat.py`, `service/`) never reads `truth/` or imports `ble.sim`/`ble.evals`.
  `tests/test_isolation.py` checks imports; `tests/test_pipeline.py` runs a tender without truth.
- Thresholds and vocabulary live in `config/`, not in code.
- Findings are decided by rules; models read. Every finding has evidence.
- Review decisions survive re-runs; a rejected finding never reaches the sheet flags or the export.
- Held-out sets: never change the engine to pass `heldout/<set>` before its first run is recorded.
  First runs in `reports/heldout/<set>/first_run.json` are not rewritten. If you study a set's
  failures, write `heldout/<set>/STATUS` = regression and have someone who has not seen the engine
  write a new set from `heldout/WRITING_BIDS.md` only.
