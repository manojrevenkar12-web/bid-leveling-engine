# Architecture

```
 tender (GAEB X83, versions)      bids (GAEB X84 · PDF · XLSX · scanned PDF) + cover letters
            │                                     │
            ▼                                     ▼
   read_tender ───────────────┐      read_bids ── route per document: gaeb │ xlsx │ pdf_text │ ocr
                              │                   words with boxes → table parser → bid lines
                              │                   OCR: tesseract deu, arithmetic repair, line confidence
                              ▼                   every value keeps Evidence(doc@sha256, page, bbox | row | xml_line)
                     resolve_positions ── which BoQ version, which position each line prices
                              │           logistic matcher over 9 features → one-to-one assignment
                              │           second pass by quantity + neighbours (always to review)
                              ▼
                     detect_deviations ── deterministic rules (config/rules.yaml): 13 deviation types,
                              │           confidence = reading × match, < 0.9 → human review
                              ▼
                        level_bids ────── Preisspiegel: comparable totals, re-ranking
                              ▼
                       build_graph ────── ontology v1 (config/ontology.yaml), lineage on every node/edge
                              │
         each step leaves a decision trace (decision-trace/1): inputs by hash, code/config/model
         version, decisions with confidence and evidence, seconds, € cost → JSONL / Langfuse
                              ▼
      `ble publish` ──► platform API (TypeScript, Fastify, Postgres) ◄── review UI (sheet, queue, ask)
                              │  decisions persist across re-runs; rejected findings leave sheet and export
                              ▼
                       AI service (Python, FastAPI): chat with citations + verifier, search, evidence crops
```

## Boundaries

| Part | Language | Owns | Never does |
|---|---|---|---|
| `src/ble/ingest`, `text`, `resolve`, `deviate`, `graph`, `harness`, `workflows.py` | Python | Reading documents and deciding findings | Read `truth/`, import `ble.sim` or `ble.evals` (`tests/test_isolation.py`) |
| `src/ble/service` | Python | Chat, search, evidence crops | Store review state |
| `platform/` | TypeScript | System of record: runs, findings, decisions, chat turns, auth, metrics | Decide findings |
| `src/ble/sim`, `src/ble/evals`, `heldout/` | Python | The simulated world, its answer key, scoring | Run in production |

The platform stores the whole run export (JSONB) and normalised rows (tender, version, position,
bid, line, finding). A re-run of a tender replaces the run but not the decisions: a finding keeps
its id when the same rule fires on the same bid and position, so a reviewer's verdict carries over.

## Why rules decide and models read

Findings change who wins a public tender. They have to be explainable to a bidder and repeatable
on the same documents, so every finding comes from a rule over extracted values, with its evidence
and the rule version (`rule: qty_changed@1`). Models are used where reading is the problem:
matching a bidder's wording to a BoQ position (a fitted logistic model, inspectable weights), OCR,
and optionally phrasing a chat answer, held to the same evidence by the verifier.

## Scaling to 10k documents a day

Measured on a 2-core container (`reports/ingest.json`, OCR seconds counted cold): GAEB and XLSX
read in milliseconds; a digital PDF in about 50 ms a page; OCR about 6 s a page at 300 dpi. At 10,000
documents a day of ~3 pages with 20% scans, OCR is ~6,000 pages ≈ 10 CPU-hours: a handful of
workers. The OCR cache is keyed by file hash, page and settings, so re-ingestion is free and
idempotent. The per-tender workflow is independent across tenders, so it shards by tender
(Prefect task per tender, `pip install .[prefect]`).
