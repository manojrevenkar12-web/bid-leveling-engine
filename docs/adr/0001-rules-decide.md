# ADR 0001: Deterministic rules decide findings; models read

Status: accepted

## Context
A finding ("missing price", "changed quantity", "reservation in the cover letter") can exclude a
bid (VOB/A § 16). It must be explainable, repeatable and auditable months later.

## Decision
Findings come from rules in `src/ble/deviate/detect.py` with thresholds in `config/rules.yaml`.
Every finding carries evidence (document hash, page and box, row or XML line), a rule version and a
confidence = how reliably the document was read × how sure the position match is. Below 0.9 it
goes to human review. Models are used for reading (OCR, the position matcher) and, optionally, for
phrasing chat answers under a verifier.

## Consequences
+ The same documents give the same findings; a reviewer can see exactly why.
+ Thresholds are business settings a customer can change without a code release.
− Rules miss phrasing they were not written for (held-out v1: 5 of 11 reservations missed on
  the first run). The held-out process exists to measure that, not to hide it.
