# Runbook

## Run locally
```
pip install -e ".[dev]"            # tesseract-ocr + tesseract-ocr-deu for scans
ble run                            # simulate, read, match, detect, level, score, gate (reports/)
docker compose up -d --build       # Postgres, platform :3000, AI service :8001
docker compose run --rm seed       # level and publish the test tenders
```

## A bid is read badly
1. Open the run: `reports/runs/<tender>.json` → `bids[].warnings`, `route`, line `confidence`.
2. Look at the trace: `reports/runs/<tender>.traces.jsonl`, step `read_bids` (route per document).
3. For a scan, the OCR text is cached at `data/.cache/ocr/<sha>-p<page>-…json`.
4. Fix in `src/ble/ingest/`, add a unit test with the failing words, re-run the tender.

## A finding is wrong
Reject it in the review UI; the decision carries over to later runs. If the rule is wrong, change
`config/rules.yaml` (thresholds) or the rule, run `ble run`, and check the gate still passes.

## Release gate fails
`reports/gate.json` lists each check. Thresholds are in `config/release.yaml`.

## Metrics
`GET /metrics` on the platform: requests by route and status, runs published, review decisions by
verdict and type, chat turns, open findings.
