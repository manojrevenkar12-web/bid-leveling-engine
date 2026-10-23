"""Entity resolution: which BoQ position does each bid line price, and which BoQ version did the
bidder price?

Bidders renumber, abbreviate, reorder and OCR garbles text, so the position number alone is not
enough. Every (bid line, BoQ position) pair is scored by a logistic model on comparable signals
(number, text in two tokenisations, character trigrams, quantity, unit, trade, order); the best
one-to-one assignment allows a line to match nothing (an added position) and a position to stay
unpriced (a missing one). Matches the model is unsure about are marked for review.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

from ble.config import MODELS, load
from ble.ingest.model import BidDoc, BidLine, TenderDoc, TenderPosition
from ble.text.de import CONSTRUCTION, PLAIN, fold, unit

FEATURES = ["oz_exact", "text_construction", "text_plain", "trigram", "qty", "qty_known", "unit", "trade", "order"]


def _vec(tokens: list[str]) -> Counter[str]:
    return Counter(tokens)


def _cos(a: Counter[str], b: Counter[str], idf: dict[str, float]) -> float:
    num = sum(a[t] * b[t] * idf.get(t, 1.0) ** 2 for t in a if t in b)
    na = math.sqrt(sum((v * idf.get(t, 1.0)) ** 2 for t, v in a.items()))
    nb = math.sqrt(sum((v * idf.get(t, 1.0)) ** 2 for t, v in b.items()))
    return num / (na * nb) if na and nb else 0.0


def _tri(s: str) -> set[str]:
    s = re.sub(r"[^a-z0-9]", "", fold(s))
    return {s[i : i + 3] for i in range(max(0, len(s) - 2))}


def _oz(s: str) -> str:
    return re.sub(r"\s", "", s)


def oz_key(s: str) -> tuple[int, ...] | None:
    """Position numbers compared by value, so a bidder's "3.10" is the BoQ's "03.0010"."""
    parts = re.findall(r"\d+", s)
    return tuple(int(x) for x in parts) if len(parts) >= 2 else None


def same_oz(shown: str, oz: str) -> bool:
    if not shown:
        return False
    if _oz(shown) == oz:
        return True
    k = oz_key(shown)
    return k is not None and k == oz_key(oz)


def units_compatible(a: str, b: str) -> bool:
    """Same canonical unit; an OCR'd "m?" (superscript not read) fits an area or a volume."""
    ua, ub = unit(a), unit(b)
    if ua == ub:
        return True
    return (a == "m?" and ub in ("m2", "m3")) or (b == "m?" and ua in ("m2", "m3"))


@dataclass
class PairFeatures:
    X: np.ndarray  # lines x positions x features


def features(bid: BidDoc, boq: TenderDoc) -> np.ndarray:
    L, P = bid.lines, boq.positions
    docs_c = [CONSTRUCTION.tokens(p.short) * 2 + CONSTRUCTION.tokens(p.long) for p in P]
    docs_p = [PLAIN.tokens(p.short) * 2 + PLAIN.tokens(p.long) for p in P]
    n = len(P)
    df_c: Counter[str] = Counter(t for d in docs_c for t in set(d))
    df_p: Counter[str] = Counter(t for d in docs_p for t in set(d))
    idf_c = {t: math.log(1 + n / c) for t, c in df_c.items()}
    idf_p = {t: math.log(1 + n / c) for t, c in df_p.items()}
    pc = [_vec(d) for d in docs_c]
    pp = [_vec(d) for d in docs_p]
    ptri = [_tri(p.short) for p in P]
    X = np.zeros((len(L), n, len(FEATURES)))
    for i, ln in enumerate(L):
        lc = _vec(CONSTRUCTION.tokens(ln.short) * 2 + CONSTRUCTION.tokens(ln.long))
        lp = _vec(PLAIN.tokens(ln.short) * 2 + PLAIN.tokens(ln.long))
        lt = _tri(ln.short)
        for j, p in enumerate(P):
            q = 0.5
            known = 0.0
            if ln.qty and p.qty:
                known = 1.0
                q = math.exp(-5 * abs(math.log(ln.qty / p.qty)))
            X[i, j] = [
                float(same_oz(ln.shown_no, p.oz)),
                _cos(lc, pc[j], idf_c),
                _cos(lp, pp[j], idf_p),
                len(lt & ptri[j]) / len(lt | ptri[j]) if lt and ptri[j] else 0.0,
                q,
                known,
                float(units_compatible(ln.unit, p.unit)),
                0.5 if not ln.trade_hint else float(ln.trade_hint == p.trade),
                1 - abs(i / max(len(L) - 1, 1) - j / max(n - 1, 1)),
            ]
    return X


@dataclass
class Matcher:
    coef: list[float]
    intercept: float
    trained_on: dict[str, Any] = field(default_factory=dict)

    def proba(self, X: np.ndarray) -> np.ndarray:
        z = X @ np.asarray(self.coef) + self.intercept
        return 1 / (1 + np.exp(-z))

    def save(self, path: Path = MODELS / "matcher.json") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=1))

    @classmethod
    def load(cls, path: Path = MODELS / "matcher.json") -> Matcher:
        if path.exists():
            return cls(**json.loads(path.read_text()))
        return cls.default()

    @classmethod
    def default(cls) -> Matcher:
        """Hand-set weights, used before `ble train` has fitted the model."""
        return cls([4.0, 6.0, 1.0, 2.0, 2.0, -0.5, 1.0, 1.0, 1.0], -9.0, {"source": "default"})


@dataclass
class Match:
    line: int
    oz: str | None
    p: float
    runner_up: str | None
    p_runner_up: float
    needs_review: bool


@dataclass
class Resolution:
    bid_id: str
    version: str
    version_scores: dict[str, float]
    version_margin: float
    matches: list[Match]
    unmatched_positions: list[str]

    def by_oz(self) -> dict[str, Match]:
        return {m.oz: m for m in self.matches if m.oz}


def assign(P: np.ndarray, p_none: float) -> list[int]:
    """Best one-to-one assignment of lines to positions; -1 = no position (cost of p_none)."""
    nl, npos = P.shape
    eps = 1e-6
    cost = np.empty((nl, npos + nl))
    cost[:, :npos] = -np.log(np.clip(P, eps, 1.0))
    dummy = np.full((nl, nl), 1e6)
    np.fill_diagonal(dummy, -math.log(max(p_none, eps)))  # each line has its own "no position" slot
    cost[:, npos:] = dummy
    r, c = linear_sum_assignment(cost)
    out = [-1] * nl
    for i, j in zip(r, c, strict=True):
        out[i] = int(j) if j < npos else -1
    return out


def _same_qty(a: float | None, b: float | None) -> bool:
    return bool(a and b and abs(a - b) <= 0.005 * b)


def residual(bid: BidDoc, boq: TenderDoc, X: np.ndarray, a: list[int]) -> set[int]:
    """Second pass over what the assignment left: a line that matched nothing and a position nobody
    priced are paired when the bid says they are the same thing: the same quantity and unit (only
    one such position left), or the only free position between the line's matched neighbours with
    a compatible unit and some shared text. Returns the lines paired this way; they go to review."""
    free = {j for j in range(len(boq.positions))} - {j for j in a if j >= 0}
    paired: set[int] = set()
    while True:  # each pairing narrows the gaps around the next, so repeat until nothing changes
        n = len(paired)
        _residual_pass(bid, boq, X, a, free, paired)
        if len(paired) == n:
            return paired


def _residual_pass(bid: BidDoc, boq: TenderDoc, X: np.ndarray, a: list[int], free: set[int], paired: set[int]) -> None:
    T = FEATURES.index("text_construction")
    for i in [i for i, j in enumerate(a) if j < 0]:
        ln = bid.lines[i]
        ok = [j for j in free if units_compatible(ln.unit, boq.positions[j].unit)]
        same = [j for j in ok if _same_qty(ln.qty, boq.positions[j].qty)]
        pick = None
        if len(same) == 1 and X[i, same[0], T] > 0.0:
            pick = same[0]
        else:
            before = [a[k] for k in range(i - 1, -1, -1) if a[k] >= 0][:1]
            after = [a[k] for k in range(i + 1, len(a)) if a[k] >= 0][:1]
            lo, hi = (before[0] if before else -1), (after[0] if after else len(boq.positions))
            gap = [j for j in ok if lo < j < hi]
            if lo < hi and len(gap) == 1 and (X[i, gap[0], T] >= 0.1 or _same_qty(ln.qty, boq.positions[gap[0]].qty)):
                pick = gap[0]
        if pick is not None:
            a[i] = pick
            free.discard(pick)
            paired.add(i)


def resolve(bid: BidDoc, versions: list[TenderDoc], matcher: Matcher | None = None) -> Resolution:
    cfg = load("rules")["matching"]
    m = matcher or Matcher.load()
    best: tuple[float, str, list[int], np.ndarray, set[int]] | None = None
    scores: dict[str, float] = {}
    for boq in versions:
        if not bid.lines or not boq.positions:
            continue
        X = features(bid, boq)
        P = m.proba(X)
        a = assign(P, cfg["p_none"])
        second = residual(bid, boq, X, a)
        matched = [(i, j) for i, j in enumerate(a) if j >= 0]
        # how well the bid fits this version: matches that agree on quantity, against everything left over
        agree = sum(1 for i, j in matched if _same_qty(bid.lines[i].qty, boq.positions[j].qty))
        left = (len(boq.positions) - len(matched)) + (len(bid.lines) - len(matched))
        s = (agree - left) / max(len(boq.positions), 1)
        scores[boq.version] = round(s, 4)
        if best is None or s > best[0]:
            best = (s, boq.version, a, P, second)
    if best is None:
        return Resolution(bid.bid_id, versions[-1].version if versions else "", {}, 0.0, [], [])
    _, ver, a, P, second = best
    boq = next(v for v in versions if v.version == ver)
    srt = sorted(scores.values(), reverse=True)
    margin = srt[0] - srt[1] if len(srt) > 1 else 1.0
    matches = []
    for i, j in enumerate(a):
        row = P[i]
        order = np.argsort(-row)
        top2 = [int(k) for k in order[:2]]
        if j >= 0:
            ru = next((k for k in top2 if k != j), None)
            p_ru = float(row[ru]) if ru is not None else 0.0
            p = float(row[j])
            review = (
                i in second
                or p < cfg["review_below"]
                or (p - p_ru) < cfg["review_margin"]
                or bid.lines[i].confidence < load("ingest")["ocr"]["low_confidence_line"]
            )
            matches.append(Match(i, boq.positions[j].oz, round(p, 4), boq.positions[ru].oz if ru is not None else None, round(p_ru, 4), bool(review)))
        else:
            p0 = float(row[top2[0]]) if len(top2) else 0.0
            matches.append(Match(i, None, round(1 - p0, 4), boq.positions[top2[0]].oz if top2 else None, round(p0, 4), bool(p0 > cfg["p_none"] * 0.6)))
    got = {mm.oz for mm in matches if mm.oz}
    return Resolution(bid.bid_id, ver, scores, round(margin, 4), matches, [p.oz for p in boq.positions if p.oz not in got])


def baseline_oz_only(bid: BidDoc, boq: TenderDoc) -> list[str | None]:
    """What matching by position number alone gives (the baseline)."""
    ozs = {p.oz for p in boq.positions}
    return [_oz(ln.shown_no) if _oz(ln.shown_no) in ozs else None for ln in bid.lines]


def line_text(ln: BidLine | TenderPosition) -> str:
    return f"{ln.short} {ln.long}".strip()
