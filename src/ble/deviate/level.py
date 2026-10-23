"""The bid leveling sheet (Preisspiegel): every bid's unit prices against the current BoQ, and totals
that can actually be compared.

A bid's own total is not comparable when it has arithmetic errors, changed quantities, missing
prices or was priced on an older BoQ version. The comparable total re-prices every current
position at the bidder's unit price (which prevails over its total) and the current quantity; a
position the bidder did not price is valued at the highest unit price any other bidder offered,
the way a missing price is weighed when bids are evaluated. The ranking shows where comparable
totals reorder the stated ones.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ble.ingest.model import BidDoc, BidLine, TenderDoc
from ble.resolve.match import Resolution


@dataclass
class Cell:
    ep: float | None
    gp_stated: float | None
    gp_comparable: float | None
    filled: bool = False  # valued at the highest other price
    flags: list[str] = field(default_factory=list)


@dataclass
class Sheet:
    tender_id: str
    version: str
    positions: list[dict[str, Any]]
    bidders: list[dict[str, Any]]
    cells: dict[str, dict[str, Cell]]  # oz -> bid_id -> cell
    ranking: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def level(versions: list[TenderDoc], bids: list[BidDoc], resolutions: list[Resolution], findings: list[Any]) -> Sheet:
    cur = versions[-1]
    flags: dict[tuple[str, str | None], list[str]] = {}
    for f in findings:
        flags.setdefault((f.bid_id, f.oz), []).append(f.type)
    eps: dict[str, dict[str, float]] = {}
    lines: dict[str, dict[str, BidLine]] = {}
    for bid, res in zip(bids, resolutions, strict=True):
        for m in res.matches:
            if m.oz:
                ln = bid.lines[m.line]
                lines.setdefault(m.oz, {})[bid.bid_id] = ln
                if ln.ep is not None and not ln.included:
                    eps.setdefault(m.oz, {})[bid.bid_id] = ln.ep
    cells: dict[str, dict[str, Cell]] = {}
    totals: dict[str, dict[str, float]] = {b.bid_id: {"comparable": 0.0, "filled": 0} for b in bids}
    for p in cur.positions:
        row: dict[str, Cell] = {}
        for b in bids:
            cl: BidLine | None = lines.get(p.oz, {}).get(b.bid_id)
            ep = None if cl is None or cl.included else cl.ep
            filled = False
            if cl is not None and cl.included:
                ep_cmp = 0.0
            elif ep is None:
                others = [v for k, v in eps.get(p.oz, {}).items() if k != b.bid_id]
                ep_cmp = max(others) if others else 0.0
                filled = True
            else:
                ep_cmp = ep
            gp_cmp = round(ep_cmp * (p.qty or 0.0), 2)
            totals[b.bid_id]["comparable"] += gp_cmp
            totals[b.bid_id]["filled"] += int(filled)
            row[b.bid_id] = Cell(ep, cl.gp if cl is not None else None, gp_cmp, filled, sorted(set(flags.get((b.bid_id, p.oz), []))))
        cells[p.oz] = row
    bidders: list[dict[str, Any]] = []
    for b, res in zip(bids, resolutions, strict=True):
        stated = b.stated_total if b.stated_total is not None else round(sum(ln.gp or 0.0 for ln in b.lines), 2)
        extras = sum(b.lines[m.line].gp or 0.0 for m in res.matches if m.oz is None)
        bidders.append(
            {
                "bid_id": b.bid_id,
                "company": b.company,
                "route": b.route,
                "priced_version": res.version,
                "stated_total": round(stated, 2),
                "comparable_total": round(totals[b.bid_id]["comparable"], 2),
                "added_positions_total": round(extras, 2),
                "positions_valued_at_highest_other_price": totals[b.bid_id]["filled"],
                "bid_level_flags": sorted({t for (bid_id, oz), ts in flags.items() if bid_id == b.bid_id and oz is None for t in ts}),
            }
        )
    by_stated = sorted(bidders, key=lambda x: x["stated_total"])
    by_cmp = sorted(bidders, key=lambda x: x["comparable_total"])
    ranking = [
        {"rank": i + 1, "bid_id": x["bid_id"], "company": x["company"], "comparable_total": x["comparable_total"], "stated_rank": by_stated.index(x) + 1}
        for i, x in enumerate(by_cmp)
    ]
    positions = [{"oz": p.oz, "trade": p.trade, "short": p.short, "qty": p.qty, "unit": p.unit} for p in cur.positions]
    return Sheet(cur.tender_id, cur.version, positions, bidders, cells, ranking)
