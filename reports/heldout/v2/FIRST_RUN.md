# Held-out set v2: first run

Run once on 2026-10-23 23:49:17. The bids were written as scripts by an agent that read only `heldout/WRITING_BIDS.md` and the
BoQs, never the engine, and rendered into the documents bidders send. This file is not regenerated; later runs go to
`latest.json`. If the engine is changed after studying these results, this set becomes a regression set and a new one is written.

**Findings: precision 84.6%, recall 86.8%** (33 found, 6 false, 5 missed).

| Deviation | Found | False | Missed |
|---|---|---|---|
| Arithmetic error (EP × qty ≠ total) | 2 | 0 | 1 |
| Position added | 2 | 0 | 0 |
| Priced as included | 2 | 0 | 0 |
| Position not priced | 2 | 1 | 0 |
| Missing price | 2 | 3 | 0 |
| Priced an outdated BoQ version | 1 | 0 | 0 |
| Unit price outlier | 2 | 0 | 0 |
| Other product than reference | 3 | 0 | 0 |
| Quantity changed | 3 | 0 | 0 |
| Reservation in cover letter | 9 | 0 | 4 |
| Long text changed (spec) | 2 | 2 | 0 |
| Speculative (unbalanced) pricing | 1 | 0 | 0 |
| Unit changed | 2 | 0 | 0 |

| Route | Lines | Matched correctly | By position number alone |
|---|---|---|---|
| gaeb | 65 | 100.0% | 100.0% |
| pdf_text | 131 | 100.0% | 50.4% |
| xlsx | 95 | 100.0% | 0.0% |
| ocr | 64 | 100.0% | 1.6% |

BoQ version identified: 11 of 11 bids.

| Search | Queries | Hit@1 | Hit@3 |
|---|---|---|---|
| plain | 25 | 20.0% | 24.0% |
| construction | 25 | 24.0% | 32.0% |

## Missed

- H93-B1 (gaeb): reservation  – escalation
- H93-B5 (pdf_text): reservation  – liability
- H94-B3 (ocr): arithmetic_error 05.0010 – 31.75 x 820 = 26035.00, printed 26305.00
- H94-B4 (xlsx): reservation  – liability
- H94-B5 (xlsx): reservation  – schedule

## False findings

- H93-B5 (pdf_text): spec_change 02.0010 – Long text of 02.0010 differs: “angebotenes fabrikat” → “”
- H94-B3 (ocr): missing_price 04.0030 – No price for 04.0030 “Asphalttragschicht AC 32 T S, d = 10 cm”.
- H94-B3 (ocr): missing_price 05.0010 – No price for 05.0010 “Hochbordstein Beton 15/30”.
- H94-B3 (ocr): missing_price 05.0050 – No price for 05.0050 “Straßenablauf 500/500, Aufsatz D 400”.
- H94-B3 (ocr): missing_position 01.0010 – 01.0010 “Baustelleneinrichtung” is not in the bid.
- H94-B6 (pdf_text): spec_change 03.0060 – Long text of 03.0060 differs: “angebotenes fabrikat” → “”

## Search queries not answered in the top 3

- Steinwolle Fassadendämmung
- Eingangstür mit Panikschloss
- Attikablech
- Dachgully
- Regenrohr Zink
- Fußleiste Fliese
- Gummiboden
- Schmutzfangmatte Eingang
- Kippgebühren belasteter Aushub
- Grundwasser abpumpen
- Baustellenampel
- Kanaldeckel
- Kamerabefahrung
- Hausanschlüsse Kanal
- Randsteine
- Gehwegplatten Pflaster
- Gullys Straße
