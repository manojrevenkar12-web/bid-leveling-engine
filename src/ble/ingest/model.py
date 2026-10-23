"""What ingestion produces: documents as lines with numbers and where each came from."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Evidence:
    """Where a value was read: a file (content hash), a page and box, a spreadsheet row, or an XML line."""

    doc: str  # document id: <tender>/<path>@<sha256[:12]>
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None  # x0, top, x1, bottom in PDF points
    row: int | None = None  # spreadsheet row
    xml_line: int | None = None
    text: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class TenderPosition:
    oz: str
    trade: str
    short: str
    long: str
    qty: float | None
    unit: str
    evidence: Evidence


@dataclass
class TenderDoc:
    tender_id: str
    version: str  # v1, v2 ... in issue order
    date: str
    label: str
    project: str
    trades: dict[str, str]
    positions: list[TenderPosition]
    doc_id: str


@dataclass
class BidLine:
    idx: int
    shown_no: str
    trade_hint: str  # the Titel the line was printed under ("" if unknown)
    short: str
    long: str
    qty: float | None
    unit: str
    ep: float | None
    gp: float | None
    included: bool
    product: str | None
    evidence: Evidence
    confidence: float = 1.0  # extraction confidence (OCR lowers it)


@dataclass
class Sentence:
    text: str
    evidence: Evidence


@dataclass
class BidDoc:
    bid_id: str
    tender_id: str
    company: str
    route: str  # gaeb, xlsx, pdf_text, ocr
    lines: list[BidLine]
    letter: list[Sentence]
    stated_total: float | None
    boq_label: str  # what the bid says it priced (GAEB only)
    doc_ids: list[str]
    pages: int
    cost_eur: float  # extraction cost (OCR / model calls), from config/ingest.yaml
    seconds: float
    warnings: list[str] = field(default_factory=list)


NUM = re.compile(r"^-?\d{1,3}(?:\.\d{3})*(?:,\d+)?$|^-?\d+(?:,\d+)?$")


def de_num(s: str) -> float | None:
    """Parse a German-formatted number ("1.234,56"); None when it is not one."""
    s = s.strip().replace("€", "").replace(" ", "")
    if not s:
        return None
    if NUM.match(s):
        return float(s.replace(".", "").replace(",", "."))
    if re.match(r"^-?\d+\.\d{1,3}$", s) and s.count(".") == 1 and len(s.split(".")[1]) != 3:
        return float(s)  # an English decimal point from a spreadsheet
    return None
