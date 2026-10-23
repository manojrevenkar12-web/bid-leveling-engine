# ADR 0003: Route each document by what it is; OCR only what has no text

Status: accepted

## Context
Bids arrive as GAEB files, spreadsheets, PDFs from estimating software and printed-and-scanned
PDFs. OCR is ~100× slower than reading a text layer and adds errors; a vision model per page
costs more again (`config/ingest.yaml`).

## Decision
Route per document and per page: GAEB and XLSX are parsed; a PDF page with a text layer is read
from it; only pages without text are OCR'd (tesseract, German model, 300 dpi). OCR'd lines use the
arithmetic a priced line must satisfy (unit price × quantity = total) to correct single misread
digits, and carry a confidence; low-confidence lines and their findings go to review. Superscripts
OCR cannot read (m², m³) become "m?" and are settled by matching against the BoQ.

## Consequences
+ Cost and time are spent where the document needs them; each route's precision is reported.
+ OCR results are cached by file hash, page and settings.
− Handwriting and photographed pages are not covered; a vision model would be the fallback route.
