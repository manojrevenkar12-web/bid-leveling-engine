"""Findings: where a bid deviates from the BoQ, and where its prices need a second look.

Rules are deterministic and every finding carries the evidence it was read from (bid line, BoQ
position, letter sentence) and a confidence that combines how reliably the document was read with
how sure the position match is. Findings below the auto-confirm threshold go to human review.
"""

from __future__ import annotations

import difflib
import hashlib
import math
import re
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from ble.config import load
from ble.ingest.model import BidDoc, Evidence, TenderDoc
from ble.resolve.match import Resolution
from ble.text.de import fold, unit

ROUTE_CONF = {"gaeb": 0.99, "xlsx": 0.98, "pdf_text": 0.96, "ocr": 0.85}


@dataclass
class Finding:
    id: str
    tender_id: str
    bid_id: str
    type: str
    oz: str | None
    severity: str
    message: str
    expected: Any = None
    found: Any = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 1.0
    needs_review: bool = False
    rule: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fid(*parts: object) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:12]


def _make(bid: BidDoc, typ: str, oz: str | None, msg: str, ev: list[Evidence], conf: float, **kw: Any) -> Finding:
    sev = load("rules")["severity"][typ]
    review = conf < load("rules")["review"]["auto_confirm_above"]
    return Finding(
        _fid(bid.bid_id, typ, oz, kw.get("detail", {}).get("key", "")),
        bid.tender_id,
        bid.bid_id,
        typ,
        oz,
        sev["severity"],
        msg,
        evidence=[e.as_dict() for e in ev],
        confidence=round(conf, 3),
        needs_review=review,
        rule=f"{typ}@1",
        **kw,
    )


# -- long-text specification comparison ----------------------------------------------------------
HIGHER = [
    "dicke",
    "starke",
    "festigkeitsklasse",
    "feuerwiderstand",
    "schalldamm",
    "rw",
    "lastklasse",
    "rutschhemmung",
    "querschnitt",
    "hohe",
    "breite",
    "lagig",
    "ubedeckung",
    "rohruberdeckung",
    "dpr",
    "klimaklasse",
    "format",
    "abhangehohe",
    "oberflachenqualitat",
    "schichtdicke",
    "wassereinwirkungsklasse",
    "absorptionsgrad",
    "gefalle",
    "homogenbereich",
]
LOWER = ["warmeleitfahigkeit", "λ", "steifigkeit", "nassabriebklasse"]
_HIGHER, _LOWER = [fold(k) for k in HIGHER], [fold(k) for k in LOWER]  # compared on folded text
CODE = re.compile(r"(?:c(\d{2})/\d{2}|rei\s?(\d{2,3})|ei\s?(\d{2,3})|f\s?(\d{2,3})|t(\d{2})|r(\d{1,2})\b|w(\d)(?:\.\d)?-|q(\d)|(?<![a-z])([ivx]+)$)")


# classes are kept as one token ("c30/37", "rei 90") so a changed class is compared as a class
TOK = re.compile(
    r"c\d{2}/\d{2}|rei\s?\d{2,3}|ei\s?\d{2,3}|f\s?\d{2,3}(?:-a)?\b|t\d{2}\b|r\d{1,2}\b|w\d(?:\.\d)?-[ie]\b|q\d\b|[a-zäöüß]+|\d+(?:[.,]\d+)?(?:/\d+)?|[λα]"
)


def _toks(s: str) -> list[str]:
    return TOK.findall(fold(s))


def _nearest(ctx: str, words: list[str]) -> int:
    """Position of the last of these keywords in the context (-1 if none)."""
    return max((ctx.rfind(k) for k in words), default=-1)


def _level(tok: str) -> float | None:
    t = fold(tok).replace(" ", "")
    m = CODE.search(t)
    if m:
        g = next(x for x in m.groups() if x)
        roman = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5}
        if g in roman:
            return float(roman[g])
        return float(g) if g.isdigit() else None
    m2 = re.fullmatch(r"(\d+)/\d+", t)
    if m2:
        return float(m2.group(1))
    try:
        return float(t.replace(",", "."))
    except ValueError:
        return None


def compare_spec(boq_long: str, bid_long: str) -> list[dict[str, Any]]:
    """Segments where the bid's long text differs from the BoQ's, with direction where known."""
    a, b = _toks(boq_long), _toks(bid_long)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        was, now = " ".join(a[i1:i2]), " ".join(b[j1:j2])
        ctx = " ".join(a[max(0, i1 - 5) : i1])
        lv_was, lv_now = _level(was) if was else None, _level(now) if now else None
        direction = "changed"
        if lv_was is not None and lv_now is not None and lv_was != lv_now:
            # the keyword nearest the changed value says which way is better
            h, lo = _nearest(ctx, _HIGHER), _nearest(ctx, _LOWER)
            hib = h > lo or (h == lo == -1 and bool(CODE.search(was)))
            lob = lo > h
            if lob:
                direction = "worse" if lv_now > lv_was else "better"
            elif hib:
                direction = "worse" if lv_now < lv_was else "better"
        out.append({"was": was, "now": now, "context": ctx, "direction": direction})
    return out


LEIT = re.compile(r"leitfabrikat:?\s*(.+?)\s+oder\s+gleichwertig", re.I)


def _sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(a=fold(a), b=fold(b)).ratio()


# -- per bid ------------------------------------------------------------------------------------
def detect_bid(bid: BidDoc, res: Resolution, versions: list[TenderDoc]) -> list[Finding]:
    R = load("rules")
    boq = next(v for v in versions if v.version == res.version)
    latest = versions[-1]
    pos = {p.oz: p for p in boq.positions}
    base = ROUTE_CONF.get(bid.route, 0.9)
    out: list[Finding] = []
    if res.version != latest.version:
        out.append(
            _make(
                bid,
                "outdated_version",
                None,
                f"Priced against BoQ {res.version} ({boq.date}); the current version is {latest.version} ({latest.date}).",
                [Evidence(boq.doc_id, text=boq.label), Evidence(latest.doc_id, text=latest.label)],
                base * min(1.0, 0.5 + res.version_margin),
                expected=latest.version,
                found=res.version,
                detail={"version_scores": res.version_scores},
            )
        )
    for m in res.matches:
        ln = bid.lines[m.line]
        conf = base * (ln.confidence if bid.route == "ocr" else 1.0) * (m.p if m.oz else max(m.p, 0.5))
        if m.oz is None:
            out.append(
                _make(
                    bid,
                    "extra_position",
                    None,
                    f"Added position not in the BoQ: “{ln.short}”.",
                    [ln.evidence],
                    conf,
                    found=ln.short,
                    detail={"key": ln.idx, "line": ln.idx},
                )
            )
            continue
        p = pos[m.oz]
        evs = [ln.evidence, p.evidence]
        dk = {"key": m.oz, "line": ln.idx, "match_p": m.p}
        if ln.included:
            out.append(_make(bid, "included_price", m.oz, f"{m.oz} priced as included (“enthalten”/0).", evs, conf, detail=dk))
        elif ln.ep is None and ln.gp is None:
            out.append(_make(bid, "missing_price", m.oz, f"No price for {m.oz} “{p.short}”.", evs, conf, detail=dk))
        if ln.qty is not None and p.qty and abs(ln.qty - p.qty) > R["quantity"]["rel_tolerance"] * p.qty:
            out.append(
                _make(
                    bid, "qty_changed", m.oz, f"Quantity for {m.oz} changed from {p.qty:g} to {ln.qty:g}.", evs, conf, expected=p.qty, found=ln.qty, detail=dk
                )
            )
        if ln.unit and unit(ln.unit) != unit(p.unit):
            out.append(
                _make(bid, "unit_changed", m.oz, f"Unit for {m.oz} changed from {p.unit} to {ln.unit}.", evs, conf, expected=p.unit, found=ln.unit, detail=dk)
            )
        if ln.ep is not None and ln.gp is not None and ln.qty is not None and not ln.included:
            calc = round(ln.ep * ln.qty, 2)
            tol = max(R["arithmetic"]["abs_tolerance_eur"], R["arithmetic"]["rel_tolerance"] * abs(calc))
            if abs(calc - ln.gp) > tol:
                out.append(
                    _make(
                        bid,
                        "arithmetic_error",
                        m.oz,
                        f"{m.oz}: {ln.ep:.2f} × {ln.qty:g} = {calc:,.2f}, but the total says {ln.gp:,.2f}; the unit price prevails.",
                        evs,
                        conf,
                        expected=calc,
                        found=ln.gp,
                        detail=dk,
                    )
                )
        if ln.long and p.long:
            diffs = compare_spec(p.long, ln.long)
            if bid.route == "ocr":  # OCR changes words; only number and class changes count
                diffs = [d for d in diffs if _level(d["was"] or "x") is not None and _level(d["now"] or "x") is not None]
            if diffs:
                worse = [d for d in diffs if d["direction"] == "worse"]
                lead = worse[0] if worse else diffs[0]
                out.append(
                    _make(
                        bid,
                        "spec_change",
                        m.oz,
                        f"Long text of {m.oz} differs: “{lead['was']}” → “{lead['now']}”" + (" (weaker specification)" if worse else ""),
                        evs,
                        conf * (1.0 if worse or len(diffs) <= 2 else 0.8),
                        expected=lead["was"],
                        found=lead["now"],
                        detail={**dk, "diffs": diffs, "direction": "worse" if worse else diffs[0]["direction"]},
                    )
                )
        mt = LEIT.search(p.long)
        if mt and ln.product:
            ref = mt.group(1).strip().rstrip(",")
            if _sim(ref, ln.product) < 0.8 and fold(ref) not in fold(ln.product):
                out.append(
                    _make(
                        bid,
                        "product_alternative",
                        m.oz,
                        f"{m.oz}: offers “{ln.product}” instead of the reference product “{ref}”.",
                        evs,
                        conf,
                        expected=ref,
                        found=ln.product,
                        detail=dk,
                    )
                )
    for oz in res.unmatched_positions:
        p = pos[oz]
        out.append(_make(bid, "missing_position", oz, f"{oz} “{p.short}” is not in the bid.", [p.evidence], base * 0.95, detail={"key": oz}))
    out += reservations(bid)
    return out


def reservations(bid: BidDoc) -> list[Finding]:
    pats = {k: [re.compile(p) for p in ps] for k, ps in load("reservations")["kinds"].items()}
    out = []
    base = ROUTE_CONF.get(bid.route, 0.9) if bid.route == "ocr" else 0.97
    for i, s in enumerate(bid.letter):
        t = fold(s.text)
        hits = [k for k, ps in pats.items() if any(p.search(t) for p in ps)]
        if hits:
            out.append(
                _make(
                    bid,
                    "reservation",
                    None,
                    f"Cover letter: “{s.text}”",
                    [s.evidence],
                    base,
                    found=hits[0],
                    detail={"key": i, "kinds": hits, "sentence": s.text},
                )
            )
    return out


# -- across bids --------------------------------------------------------------------------------
def detect_tender(bids: list[BidDoc], resolutions: list[Resolution], versions: list[TenderDoc]) -> list[Finding]:
    """Price outliers and speculative pricing, which only show against the other bids."""
    R = load("rules")
    allpos = {p.oz: p for v in versions for p in v.positions}
    eps: dict[str, dict[str, tuple[float, Evidence]]] = {}
    for bid, res in zip(bids, resolutions, strict=True):
        for m in res.matches:
            ln = bid.lines[m.line]
            if m.oz and ln.ep and ln.ep > 0 and not ln.included:
                eps.setdefault(m.oz, {})[bid.bid_id] = (ln.ep, ln.evidence)
    out: list[Finding] = []
    by_id = {b.bid_id: b for b in bids}
    O = R["outliers"]
    ratios: dict[str, dict[str, float]] = {}
    for oz, d in eps.items():
        if len(d) < O["min_bids"]:
            continue
        for bid_id, (ep, ev) in d.items():
            others = [v[0] for k, v in d.items() if k != bid_id]
            med = statistics.median(others)
            r = ep / med
            ratios.setdefault(bid_id, {})[oz] = r
            if r >= O["high_ratio"] or r <= O["low_ratio"]:
                b = by_id[bid_id]
                p = allpos[oz]
                out.append(
                    _make(
                        b,
                        "price_outlier",
                        oz,
                        f"{oz} “{p.short}”: unit price {ep:,.2f} is {r:.1f}× the other bidders' median ({med:,.2f}).",
                        [ev, p.evidence],
                        ROUTE_CONF.get(b.route, 0.9),
                        expected=round(med, 2),
                        found=ep,
                        detail={"key": oz, "ratio": round(r, 3), "n_bids": len(d)},
                    )
                )
    S = R["speculative"]
    kw = [fold(k) for k in S["risk_keywords"]]
    for bid_id, rs in ratios.items():
        if len(rs) < S["min_positions"]:
            continue
        ozs = sorted(rs)
        lr = np.log([rs[o] for o in ozs])
        risk = np.array([float(any(k in fold(allpos[o].short + " " + allpos[o].long) for k in kw)) for o in ozs])
        if not 0 < risk.sum() < len(risk):
            continue  # without positions whose quantities tend to grow there is nothing to speculate on
        corr = float(np.corrcoef(lr, risk)[0, 1])
        loading = float(lr[risk == 1].mean() - lr[risk == 0].mean())
        if corr >= S["risk_correlation"] and loading >= S["loading"]:
            b = by_id[bid_id]
            top = sorted((o for o, k in zip(ozs, risk, strict=True) if k), key=lambda o: -rs[o])[:3]
            out.append(
                _make(
                    b,
                    "speculative_pricing",
                    None,
                    f"Unbalanced pricing: positions whose quantities tend to grow ({', '.join(top)}) are priced {math.exp(loading):.1f}× higher, relative to the field, than the rest (r = {corr:.2f}).",
                    [b.lines[0].evidence] if b.lines else [],
                    0.85,
                    detail={"key": "bid", "risk_correlation": round(corr, 3), "loading": round(loading, 3), "highest": top},
                )
            )
    return out
