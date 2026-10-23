"""Score findings and position matches against the simulator's answer key."""

from __future__ import annotations

import difflib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from ble.evals import truth
from ble.resolve.match import baseline_oz_only
from ble.text.de import fold
from ble.workflows import TenderResult

# truth deviation type -> finding type
MAP = {
    "missing_price": "missing_price",
    "included_price": "included_price",
    "arithmetic_error": "arithmetic_error",
    "qty_changed": "qty_changed",
    "unit_changed": "unit_changed",
    "missing_position": "missing_position",
    "extra_position": "extra_position",
    "spec_downgrade": "spec_change",
    "product_alternative": "product_alternative",
    "price_outlier": "price_outlier",
    "speculative_pricing": "speculative_pricing",
    "outdated_version": "outdated_version",
    "reservation": "reservation",
}
TYPES = sorted(set(MAP.values()))


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None

    def as_dict(self) -> dict[str, Any]:
        r = lambda x: None if x is None else round(x, 4)  # noqa: E731
        return {"tp": self.tp, "fp": self.fp, "fn": self.fn, "precision": r(self.precision), "recall": r(self.recall)}


@dataclass
class Score:
    by_type: dict[str, Counts] = field(default_factory=lambda: defaultdict(Counts))
    by_route: dict[str, Counts] = field(default_factory=lambda: defaultdict(Counts))
    matching: dict[str, dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    versions: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    review: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    misses: list[dict[str, Any]] = field(default_factory=list)
    false_alarms: list[dict[str, Any]] = field(default_factory=list)

    def total(self) -> Counts:
        c = Counts()
        for v in self.by_type.values():
            c.tp, c.fp, c.fn = c.tp + v.tp, c.fp + v.fp, c.fn + v.fn
        return c

    def as_dict(self) -> dict[str, Any]:
        m = {k: dict(v) for k, v in self.matching.items()}
        for v in m.values():
            n = v.get("lines", 0)
            v["accuracy"] = round(v.get("correct", 0) / n, 4) if n else None
            v["oz_only_accuracy"] = round(v.get("oz_only_correct", 0) / n, 4) if n else None
        return {
            "findings": {t: self.by_type[t].as_dict() for t in TYPES},
            "total": self.total().as_dict(),
            "by_route": {k: v.as_dict() for k, v in sorted(self.by_route.items())},
            "matching": m,
            "versions": dict(self.versions),
            "review": dict(self.review),
            "misses": self.misses[:60],
            "false_alarms": self.false_alarms[:60],
        }




def score_tender(r: TenderResult, s: Score | None = None) -> Score:
    s = s or Score()
    for bid, res in zip(r.bids, r.resolutions, strict=True):
        tb = truth.bid(bid.tender_id, bid.bid_id)
        route = bid.route
        # matching
        lt = truth.line_truth(bid)
        base = baseline_oz_only(bid, next(v for v in r.versions if v.version == res.version))
        M = s.matching[route]
        for mm, t, b in zip(res.matches, lt, base, strict=True):
            if t is False:
                M["unreadable"] += 1
                continue
            M["lines"] += 1
            M["correct"] += int(mm.oz == t)
            M["oz_only_correct"] += int(b == t)
            M["review"] += int(mm.needs_review)
            M["wrong_not_flagged"] += int(mm.oz != t and not mm.needs_review)
        M["truth_lines"] += len(tb["lines"])
        s.versions["correct" if res.version == tb["priced_version"] else "wrong"] += 1
        # findings
        fs = [f for f in r.findings if f.bid_id == bid.bid_id]
        devs = [d for d in tb["deviations"]]
        used: set[int] = set()
        for d in devs:
            typ = MAP[d["type"]]
            cands = [i for i, f in enumerate(fs) if i not in used and f.type == typ]
            hit = None
            if d["oz"] is not None:
                hit = next((i for i in cands if fs[i].oz == d["oz"]), None)
            elif typ == "extra_position":
                hit = max(cands, key=lambda i: difflib.SequenceMatcher(a=fold(str(fs[i].found)), b=fold(d["detail"])).ratio(), default=None)
            elif typ == "reservation":
                hit = next((i for i in cands if d["detail"] in fs[i].detail.get("kinds", [])), None) or (cands[0] if cands else None)
            else:
                hit = cands[0] if cands else None
            if hit is None:
                s.by_type[typ].fn += 1
                s.by_route[route].fn += 1
                s.misses.append({"bid": bid.bid_id, "route": route, "type": typ, "oz": d["oz"], "detail": d["detail"]})
            else:
                used.add(hit)
                s.by_type[typ].tp += 1
                s.by_route[route].tp += 1
                s.review["true_needs_review" if fs[hit].needs_review else "true_auto"] += 1
        for i, f in enumerate(fs):
            if i in used:
                continue
            s.by_type[f.type].fp += 1
            s.by_route[route].fp += 1
            s.review["false_needs_review" if f.needs_review else "false_auto"] += 1
            s.false_alarms.append({"bid": bid.bid_id, "route": route, "type": f.type, "oz": f.oz, "message": f.message[:160]})
    return s
