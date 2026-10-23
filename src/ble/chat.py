"""Evidence-linked chat over a leveled tender.

A question is routed to tools (findings by bidder or type, the ranking, unit prices for a searched
position, what changed between BoQ versions). Every sentence of the answer cites evidence the tools
returned ([E1], [E2] ...), and a verifier drops any sentence citing evidence that was not returned:
"not found" is an answer, an unsupported claim is not. A language model can phrase the answer
(`BLE_CHAT_MODEL`), under the same verifier; the default is deterministic.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from ble.llm.phrase import phrase
from ble.text.de import BM25, CONSTRUCTION, fold

TYPE_WORDS = {
    "missing_price": ["fehlende preis", "ohne preis", "missing price", "not priced", "unpriced"],
    "arithmetic_error": ["rechenfehler", "arithmetic", "calculation"],
    "qty_changed": ["menge", "quantit"],
    "unit_changed": ["einheit", "unit"],
    "missing_position": ["fehlende position", "missing position", "not in the bid"],
    "extra_position": ["zusätzliche", "added position", "extra position", "zusatz"],
    "spec_change": ["langtext", "spezifikation", "spec", "long text", "downgrade"],
    "product_alternative": ["fabrikat", "product", "produkt", "gleichwertig"],
    "price_outlier": ["ausreißer", "outlier", "auffällig", "unusual"],
    "speculative_pricing": ["spekulat", "speculative", "unbalanced"],
    "outdated_version": ["version", "nachtrag", "outdated", "veraltet"],
    "reservation": ["vorbehalt", "reservation", "anschreiben", "cover letter", "condition"],
    "included_price": ["enthalten", "included"],
}


DEVIATE_WORDS = ["deviat", "abweich", "weicht", "differ", "findings", "problem", "auffall"]


@dataclass
class Citation:
    ref: str
    doc: str
    page: int | None = None
    bbox: list[float] | None = None
    row: int | None = None
    xml_line: int | None = None
    text: str = ""


@dataclass
class Answer:
    question: str
    intent: str
    text: str
    citations: list[Citation]
    dropped: int = 0  # sentences removed because their citation was not returned by a tool
    tools: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class Evidence:
    def __init__(self) -> None:
        self.items: list[Citation] = []

    def cite(self, ev: dict[str, Any]) -> str:
        ref = f"E{len(self.items) + 1}"
        self.items.append(Citation(ref, ev.get("doc", ""), ev.get("page"), ev.get("bbox"), ev.get("row"), ev.get("xml_line"), ev.get("text", "")[:200]))
        return f"[{ref}]"


def _bid(run: dict[str, Any], q: str) -> dict[str, Any] | None:
    fq = fold(q)
    best, score = None, 0
    for b in run["bids"]:
        words = [w for w in re.findall(r"[a-z0-9]+", fold(b["company"])) if len(w) > 3 and w not in ("gmbh", "bau", "mbh")]
        s = sum(1 for w in words if w in fq) + (3 if fold(b["bid_id"]) in fq else 0)
        if s > score:
            best, score = b, s
    return best


def _types(q: str) -> list[str]:
    fq = fold(q)
    return [t for t, ws in TYPE_WORDS.items() if any(fold(w) in fq for w in ws)]


def answer(run: dict[str, Any], question: str, complete: Callable[[str], str] | None = None) -> Answer:
    q = question.strip()
    fq = fold(q)
    ev = Evidence()
    lines: list[str] = []
    tools: list[str] = []
    bid = _bid(run, q)
    types = _types(q)
    if any(w in fq for w in ("ranking", "rangfolge", "gunstig", "cheapest", "lowest", "best bid", "billigst", "vergabe")):
        intent = "ranking"
        tools.append("sheet.ranking")
        sheet = run["sheet"]
        by = {b["bid_id"]: b for b in sheet["bidders"]}
        for r in sheet["ranking"][:5]:
            b = by[r["bid_id"]]
            src = next(x for x in run["bids"] if x["bid_id"] == r["bid_id"])
            first = src["lines"][0]["evidence"] if src["lines"] else {"doc": src["doc_ids"][-1]}
            moved = "" if r["stated_rank"] == r["rank"] else f" (rank {r['stated_rank']} by its own total of {b['stated_total']:,.2f} €)"
            lines.append(f"{r['rank']}. {b['company']}: comparable total {r['comparable_total']:,.2f} €{moved}. {ev.cite(first)}")
        lines.append("Comparable totals re-price every current position at the bidder's unit price; unpriced positions are valued at the highest other price.")
    elif any(w in fq for w in ("version", "nachtrag", "geandert zwischen", "changed between", "addendum")) and len(run["versions"]) > 1:
        intent = "versions"
        tools.append("versions.diff")
        a, b = run["versions"][-2], run["versions"][-1]
        pa, pb = {p["oz"]: p for p in a["positions"]}, {p["oz"]: p for p in b["positions"]}
        for oz in sorted(set(pb) - set(pa)):
            lines.append(f"Added in {b['version']}: {oz} {pb[oz]['short']}. {ev.cite(pb[oz]['evidence'])}")
        for oz in sorted(set(pa) - set(pb)):
            lines.append(f"Removed in {b['version']}: {oz} {pa[oz]['short']}. {ev.cite(pa[oz]['evidence'])}")
        for oz in sorted(set(pa) & set(pb)):
            if pa[oz]["qty"] != pb[oz]["qty"]:
                lines.append(f"{oz} quantity {pa[oz]['qty']:g} → {pb[oz]['qty']:g} {pb[oz]['unit']}. {ev.cite(pb[oz]['evidence'])}")
            elif pa[oz]["long"] != pb[oz]["long"]:
                lines.append(f"{oz} long text changed. {ev.cite(pb[oz]['evidence'])}")
        olds = [x for x in run["bids"] if x["priced_version"] != b["version"]]
        for x in olds:
            lines.append(f"{x['company']} priced {x['priced_version']}. {ev.cite({'doc': x['doc_ids'][-1], 'text': 'bid document'})}")
    elif bid is None and not types and any(w in fq for w in DEVIATE_WORDS):
        intent = "unknown_bidder"
        tools.append("bids.list")
        lines.append("No bidder in this tender matches the name in the question. The bidders are: " + ", ".join(b["company"] for b in run["bids"]) + ".")
    elif bid is not None or types:
        intent = "findings"
        tools.append("findings.filter")
        fs = [f for f in run["findings"] if (bid is None or f["bid_id"] == bid["bid_id"]) and (not types or f["type"] in types)]
        if not fs:
            who = bid["company"] if bid else "any bid"
            lines.append(f"No findings for {who}" + (f" of type {', '.join(types)}" if types else "") + ".")
        order = {"high": 0, "medium": 1, "low": 2}
        for f in sorted(fs, key=lambda f: (order.get(f["severity"], 3), f["oz"] or ""))[:12]:
            who = "" if bid else f"{next(x['company'] for x in run['bids'] if x['bid_id'] == f['bid_id'])}: "
            review = " (awaiting review)" if f["needs_review"] else ""
            lines.append(f"{who}{f['message']}{review} {ev.cite(f['evidence'][0]) if f['evidence'] else ''}".strip())
        if len(fs) > 12:
            lines.append(f"… and {len(fs) - 12} more findings.")
    else:
        intent = "prices"
        tools.append("search.positions")
        pos = run["versions"][-1]["positions"]
        idx = BM25([CONSTRUCTION.tokens(p["short"]) * 2 + CONSTRUCTION.tokens(p["long"]) for p in pos])
        hits = idx.top(CONSTRUCTION.tokens(q), 2)
        if not hits:
            lines.append("I could not find a BoQ position for that. Ask about a bidder, a kind of deviation, the ranking, or a building part.")
        for i, _ in hits:
            p = pos[i]
            lines.append(f"{p['oz']} {p['short']} ({p['qty']:g} {p['unit']}): {ev.cite(p['evidence'])}")
            for b in run["bids"]:
                ln = next((x for x in b["lines"] if x["oz"] == p["oz"]), None)
                if ln is None:
                    lines.append(f"  {b['company']}: not priced.")
                elif ln["ep"] is None:
                    lines.append(f"  {b['company']}: no unit price. {ev.cite(ln['evidence'])}")
                else:
                    lines.append(f"  {b['company']}: {ln['ep']:,.2f} € / {ln['unit']}. {ev.cite(ln['evidence'])}")
    text, dropped = verify("\n".join(lines), ev)
    phrased = phrase(q, text, complete)
    if phrased:
        t2, d2 = verify(phrased, ev)
        if t2:
            text, dropped, tools = t2, dropped + d2, [*tools, "llm.phrase"]
    return Answer(q, intent, text, ev.items, dropped, tools)


def verify(text: str, ev: Evidence) -> tuple[str, int]:
    """Drop any line citing evidence that no tool returned."""
    known = {c.ref for c in ev.items}
    kept, dropped = [], 0
    for line in text.splitlines():
        refs = re.findall(r"\[(E\d+)\]", line)
        if any(r not in known for r in refs):
            dropped += 1
            continue
        kept.append(line)
    return "\n".join(kept), dropped
