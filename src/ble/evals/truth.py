"""The simulator's answer key, and how ingested lines line up with it. Only evaluation reads this."""

from __future__ import annotations

import json
from functools import cache
from typing import Any

from ble.config import TRUTH
from ble.ingest.model import BidDoc


@cache
def bid(tender: str, bid_id: str) -> dict[str, Any]:
    return json.loads((TRUTH / "tenders" / tender / "bids" / f"{bid_id}.json").read_text(encoding="utf-8"))


def align(doc: BidDoc) -> list[int | None]:
    """For each ingested line, the index of the truth line it reproduces (None if it reproduces
    none, e.g. an OCR fragment). Order is preserved, so this is a sequence alignment."""
    tl = bid(doc.tender_id, doc.bid_id)["lines"]
    a, b = doc.lines, tl
    n, m = len(a), len(b)

    def sim(i: int, j: int) -> float:
        x, y = a[i], b[j]
        s = 0.0
        if x.qty is not None and abs(x.qty - y["qty"]) < 0.01:
            s += 1
        if x.ep is not None and y["ep"] is not None and abs(x.ep - y["ep"]) < 0.011:
            s += 1
        if x.gp is not None and y["gp"] is not None and abs(x.gp - y["gp"]) < 0.011:
            s += 1
        if x.shown_no and x.shown_no == y["shown_no"]:
            s += 1
        return s

    D = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            D[i][j] = max(D[i - 1][j], D[i][j - 1], D[i - 1][j - 1] + (sim(i - 1, j - 1) if sim(i - 1, j - 1) >= 1 else -1))
    out: list[int | None] = [None] * n
    i, j = n, m
    while i > 0 and j > 0:
        s = sim(i - 1, j - 1)
        if s >= 1 and D[i][j] == D[i - 1][j - 1] + s:
            out[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif D[i][j] == D[i - 1][j]:
            i -= 1
        else:
            j -= 1
    return out


def line_truth(doc: BidDoc) -> list[str | bool | None]:
    """The BoQ position each ingested line really prices; None = an added position; False = the
    line reproduces no truth line."""
    tl = bid(doc.tender_id, doc.bid_id)["lines"]
    return [tl[k]["boq_oz"] if k is not None else False for k in align(doc)]
