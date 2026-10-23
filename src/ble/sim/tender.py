"""Tenders and bids with known deviations (simulator only).

A tender is a bill of quantities (BoQ) issued in one or two versions (v2 = an addendum during the
bidding period). Each bidder prices one version, in its own format and habits, and introduces the
deviations its persona makes likely. Every deviation is recorded in the bid's truth record.
"""

from __future__ import annotations

import copy
import re
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from ble.config import world

PROJECTS = [
    "Neubau Kita Lichtenberg",
    "Erweiterung Grundschule Pankow",
    "Wohnanlage Am Mühlenfließ",
    "Bürogebäude Hafenstraße 12",
    "Sanierung Rathaus Köpenick",
    "Neubau Feuerwache Nord",
    "Mehrfamilienhaus Gartenstadt",
    "Sporthalle Marzahn",
    "Pflegeheim Am Schlosspark",
    "Laborgebäude Adlershof",
    "Wohn- und Geschäftshaus Lindenstraße",
    "Neubau Gesundheitszentrum Spandau",
]


@dataclass
class Position:
    oz: str  # ordinal number in the BoQ, e.g. 03.0040
    trade: str
    template: str
    short: str
    long: str
    unit: str
    qty: float
    attrs: dict[str, str] = field(default_factory=dict)  # slot -> value as tendered
    product: str | None = None  # Leitfabrikat, when the position names one
    risk: float = 0.0
    fair_ep: float = 0.0  # simulator's fair unit price (truth)


@dataclass
class BoQ:
    tender_id: str
    project: str
    version: str
    trades: dict[str, str]
    positions: list[Position]

    def by_oz(self) -> dict[str, Position]:
        return {p.oz: p for p in self.positions}


@dataclass
class BidLine:
    """One priced line as the bidder wrote it."""

    shown_no: str  # what the bidder printed as position number ("" if none)
    boq_oz: str | None  # the BoQ position it prices (truth); None for an added position
    trade: str
    short: str
    long: str | None
    unit: str
    qty: float
    ep: float | None  # None = left blank
    gp: float | None
    included: bool = False  # "enthalten" instead of a price
    product: str | None = None  # Bieterangabe: offered product


@dataclass
class Deviation:
    type: str
    oz: str | None  # BoQ position (None for bid-level findings)
    detail: str = ""


@dataclass
class Bid:
    bid_id: str
    tender_id: str
    company: str
    persona: str
    format: str
    priced_version: str
    layout: dict[str, bool]
    lines: list[BidLine]
    reservations: list[dict[str, str]]
    letter: list[str]
    deviations: list[Deviation]

    def truth(self) -> dict[str, Any]:
        d = asdict(self)
        d["lines"] = [asdict(x) for x in self.lines]
        d["deviations"] = [asdict(x) for x in self.deviations]
        return d


def _fill(text: str, attrs: dict[str, str]) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: attrs[m.group(1)], text)


def _qty(rng: np.random.Generator, lo: float, hi: float, unit: str) -> float:
    if lo == hi:
        return float(lo)
    q = float(rng.uniform(lo, hi))
    if unit in ("St", "psch", "Wo"):
        return float(max(1, round(q)))
    if unit in ("t", "m3", "h"):
        return round(q, 1)
    return float(round(q))


def make_boq(tender_id: str, rng: np.random.Generator) -> list[BoQ]:
    """Version 1 and, for some tenders, an addendum version 2."""
    w, lib = world("world"), world("positions")
    trades_all = sorted(lib["trades"])
    n_tr = int(rng.integers(w["tenders"]["trades"][0], w["tenders"]["trades"][1] + 1))
    trades = sorted(rng.choice(trades_all, size=n_tr, replace=False).tolist())
    n_pos = int(rng.integers(w["tenders"]["positions"][0], w["tenders"]["positions"][1] + 1))
    pool = [t for t in lib["positions"] if t["trade"] in trades]
    n_pos = min(n_pos, len(pool))
    picked = rng.choice(len(pool), size=n_pos, replace=False)
    chosen = sorted((pool[i] for i in picked), key=lambda t: (t["trade"], lib["positions"].index(t)))
    positions: list[Position] = []
    seq: dict[str, int] = {}
    for t in chosen:
        seq[t["trade"]] = seq.get(t["trade"], 0) + 1
        attrs, product = {}, None
        for slot, spec in (t.get("attrs") or {}).items():
            vals = spec["values"]
            if spec.get("product"):
                attrs[slot] = vals[0]
                product = vals[0]
            else:  # leave room for a downgrade: never tender the weakest value
                attrs[slot] = vals[int(rng.integers(0, max(1, len(vals) - 1)))]
        fair = float(rng.uniform(*t["ep"]))
        positions.append(
            Position(
                oz=f"{t['trade']}.{seq[t['trade']] * 10:04d}",
                trade=t["trade"],
                template=t["id"],
                short=t["short"],
                long=_fill(t["long"], attrs),
                unit=t["unit"],
                qty=_qty(rng, t["qty"][0], t["qty"][1], t["unit"]),
                attrs=attrs,
                product=product,
                risk=float(t["risk"]),
                fair_ep=round(fair, 2),
            )
        )
    project = PROJECTS[int(rng.integers(len(PROJECTS)))]
    names = {k: lib["trades"][k] for k in trades}
    v1 = BoQ(tender_id, project, "v1", names, positions)
    out = [v1]
    if rng.random() < w["tenders"]["addendum_rate"]:
        out.append(_addendum(v1, pool, chosen, rng))
    return out


def _addendum(v1: BoQ, pool: list[dict[str, Any]], chosen: list[dict[str, Any]], rng: np.random.Generator) -> BoQ:
    a = world("world")["tenders"]["addendum"]
    v2 = copy.deepcopy(v1)
    v2.version = "v2"
    ps = v2.positions
    for i in rng.choice(len(ps), size=min(len(ps), int(rng.integers(a["qty_changes"][0], a["qty_changes"][1] + 1))), replace=False):
        p = ps[int(i)]
        if p.unit != "psch":
            p.qty = _qty(rng, p.qty * 1.15, p.qty * 1.6, p.unit) if rng.random() < 0.6 else _qty(rng, p.qty * 0.5, p.qty * 0.85, p.unit)
    n_rm = int(rng.integers(a["removed"][0], a["removed"][1] + 1))
    for i in sorted(rng.choice(len(ps), size=min(n_rm, len(ps) - 5), replace=False).tolist(), reverse=True):
        del ps[int(i)]
    unused = [t for t in pool if t not in chosen]
    n_add = min(len(unused), int(rng.integers(a["added"][0], a["added"][1] + 1)))
    for i in rng.choice(len(unused), size=n_add, replace=False) if n_add else []:
        t = unused[int(i)]
        last = max(int(p.oz.split(".")[1]) for p in ps if p.trade == t["trade"])
        attrs, product = {}, None
        for slot, spec in (t.get("attrs") or {}).items():
            attrs[slot] = spec["values"][0]
            product = spec["values"][0] if spec.get("product") else product
        ps.append(
            Position(
                oz=f"{t['trade']}.{last + 10:04d}",
                trade=t["trade"],
                template=t["id"],
                short=t["short"],
                long=_fill(t["long"], attrs),
                unit=t["unit"],
                qty=_qty(rng, t["qty"][0], t["qty"][1], t["unit"]),
                attrs=attrs,
                product=product,
                risk=float(t["risk"]),
                fair_ep=round(float(rng.uniform(*t["ep"])), 2),
            )
        )
    ps.sort(key=lambda p: p.oz)
    lib = {t["id"]: t for t in world("positions")["positions"]}
    for i in rng.choice(len(ps), size=int(rng.integers(a["text_changes"][0], a["text_changes"][1] + 1)), replace=False):
        p = ps[int(i)]
        t = lib[p.template]
        slots = [s for s, sp in (t.get("attrs") or {}).items() if not sp.get("product")]
        if slots:
            s = slots[int(rng.integers(len(slots)))]
            vals = t["attrs"][s]["values"]
            p.attrs[s] = vals[0]
            p.long = _fill(t["long"], p.attrs)
    return v2


def _money(x: float) -> float:
    return round(x + 1e-9, 2)


def make_bids(boqs: list[BoQ], rng: np.random.Generator, first_bid_no: int = 1) -> list[Bid]:
    w = world("world")
    lib = {t["id"]: t for t in world("positions")["positions"]}
    latest = boqs[-1]
    n = int(rng.integers(w["bidders_per_tender"][0], w["bidders_per_tender"][1] + 1))
    companies = rng.choice(w["companies"], size=n, replace=False).tolist()
    names = list(w["personas"])
    weights = np.array([w["personas"][k]["weight"] for k in names])
    fmts = list(w["formats"])
    fw = np.array([w["formats"][k] for k in fmts])
    bids = []
    for k, company in enumerate(companies):
        persona = str(rng.choice(names, p=weights / weights.sum()))
        if persona == "outdated" and len(boqs) == 1:
            persona = "solid"
        P = w["personas"][persona]
        fmt = str(rng.choice(fmts, p=fw / fw.sum()))
        L = w["layout"]
        layout = {
            "own_numbering": fmt in ("pdf", "xlsx", "scan") and rng.random() < L["own_numbering"],
            "no_numbering": fmt in ("pdf", "xlsx", "scan") and rng.random() < L["no_numbering"],
            "abbreviate": fmt != "gaeb" and rng.random() < L["abbreviate"],
            "include_long_text": fmt == "gaeb" or (fmt in ("pdf", "scan") and rng.random() < L["include_long_text"]),
            "reorder": fmt != "gaeb" and rng.random() < L["reorder_within_trade"],
        }
        boq = boqs[0] if persona == "outdated" else latest
        level = float(rng.uniform(*P["price_level"]))
        devs: list[Deviation] = []
        if persona == "outdated":
            devs.append(Deviation("outdated_version", None, f"priced {boq.version}, latest is {latest.version}"))
        lines: list[BidLine] = []
        for p in boq.positions:
            if rng.random() < P["missing_position"]:
                devs.append(Deviation("missing_position", p.oz))
                continue
            ep = p.fair_ep * level * float(rng.lognormal(0, 0.10))
            if P["speculative"]:
                ep *= float(rng.uniform(1.6, 2.2)) if p.risk >= 0.6 else (float(rng.uniform(0.65, 0.85)) if p.risk <= 0.3 else 1.0)
            if rng.random() < P["outlier"]:
                f = float(rng.uniform(2.8, 4.0)) if rng.random() < 0.5 else float(rng.uniform(0.15, 0.3))
                ep *= f
                devs.append(Deviation("price_outlier", p.oz, f"x{f:.2f} of the bidder's normal price"))
            ep = _money(ep)
            qty, unit, long_ = p.qty, p.unit, p.long
            if p.unit != "psch" and rng.random() < P["qty_changed"]:
                qty = _qty(rng, p.qty * 0.6, p.qty * 0.92, p.unit)
                if qty != p.qty:
                    devs.append(Deviation("qty_changed", p.oz, f"{p.qty:g} -> {qty:g}"))
            if rng.random() < P["unit_changed"]:
                alt = {"m2": "m", "m3": "m2", "m": "St", "St": "psch", "t": "kg", "h": "Tag"}.get(p.unit)
                if alt:
                    unit = alt
                    devs.append(Deviation("unit_changed", p.oz, f"{p.unit} -> {unit}"))
            if layout["include_long_text"] and rng.random() < P["spec_downgrade"]:
                t = lib[p.template]
                opts = [(s, sp) for s, sp in (t.get("attrs") or {}).items() if not sp.get("product") and sp["values"].index(p.attrs[s]) < len(sp["values"]) - 1]
                if opts:
                    s, sp = opts[int(rng.integers(len(opts)))]
                    worse = sp["values"][int(rng.integers(sp["values"].index(p.attrs[s]) + 1, len(sp["values"])))]
                    a2 = dict(p.attrs)
                    a2[s] = worse
                    long_ = _fill(t["long"], a2)
                    devs.append(Deviation("spec_downgrade", p.oz, f"{s}: {p.attrs[s]} -> {worse}"))
            product = None
            if p.product:
                if rng.random() < P["product_alt"]:
                    alts = [
                        v
                        for v in lib[p.template]["attrs"][next(s for s, sp in lib[p.template]["attrs"].items() if sp.get("product"))]["values"]
                        if v != p.product
                    ]
                    product = alts[0] if alts else None
                    if product:
                        devs.append(Deviation("product_alternative", p.oz, f"{p.product} -> {product}"))
                elif rng.random() < 0.6:
                    product = p.product
            included = False
            ep_out: float | None = ep
            gp: float | None = _money(ep * qty)
            r = rng.random()
            if r < P["missing_price"]:
                ep_out, gp = None, None
                devs.append(Deviation("missing_price", p.oz))
            elif r < P["missing_price"] + P["included"]:
                ep_out, gp, included = 0.0, 0.0, True
                devs.append(Deviation("included_price", p.oz))
            elif rng.random() < P["arithmetic"]:
                wrong = _arith_error(gp or 0.0, rng)
                devs.append(Deviation("arithmetic_error", p.oz, f"GP {wrong:.2f} instead of {gp:.2f}"))
                gp = wrong
            lines.append(BidLine(p.oz, p.oz, p.trade, p.short, long_ if layout["include_long_text"] else None, unit, qty, ep_out, gp, included, product))
        lo, hi = P["extra_positions"]
        for _ in range(int(rng.integers(lo, hi + 1))):
            e = w["extra_positions"][int(rng.integers(len(w["extra_positions"])))]
            tr = sorted({ln.trade for ln in lines})
            trade = tr[int(rng.integers(len(tr)))]
            ep = _money(float(rng.uniform(*e["ep"])))
            q = 1.0 if e["unit"] == "psch" else float(rng.integers(2, 20))
            nxt = max(int(ln.shown_no.split(".")[1]) for ln in lines if ln.trade == trade) + 10
            oz = f"{trade}.{nxt:04d}"
            lines.append(BidLine(oz, None, trade, e["short"], None, e["unit"], q, ep, _money(ep * q)))
            devs.append(Deviation("extra_position", None, e["short"]))
        if P["speculative"] and any(p.risk >= 0.6 for p in boq.positions):
            # without positions whose quantities tend to grow, this bidder is merely cheaper
            devs.append(Deviation("speculative_pricing", None, "margin loaded onto positions likely to grow"))
        lines.sort(key=lambda ln: (ln.trade, ln.shown_no))
        if layout["reorder"]:
            lines = _reorder(lines, rng)
        _number(lines, layout)
        if layout["abbreviate"]:
            for ln in lines:
                ln.short = _abbreviate(ln.short, w["abbreviations"])
        reservations = []
        if rng.random() < P["reservation"]:
            k_res = 1 + int(rng.random() < 0.35)
            for i in rng.choice(len(w["reservations"]), size=k_res, replace=False):
                reservations.append(w["reservations"][int(i)])
                devs.append(Deviation("reservation", None, w["reservations"][int(i)]["kind"]))
        neutral = rng.choice(w["neutral_sentences"], size=int(rng.integers(2, 5)), replace=False).tolist()
        letter = [neutral[0]] + [r["text"] for r in reservations] + neutral[1:]
        if len(letter) > 2:
            mid = letter[1:]
            rng.shuffle(mid)
            letter = [letter[0], *mid]
        bids.append(
            Bid(f"{latest.tender_id}-B{first_bid_no + k}", latest.tender_id, company, persona, fmt, boq.version, layout, lines, reservations, letter, devs)
        )
    return bids


def _arith_error(gp: float, rng: np.random.Generator) -> float:
    s = f"{gp:.2f}"
    digits = [i for i, c in enumerate(s) if c.isdigit()]
    if len(digits) >= 3 and rng.random() < 0.5:  # transposed digits
        i = digits[int(rng.integers(0, len(digits) - 3))]
        j = i + 1 if s[i + 1].isdigit() else i + 2
        if s[i] != s[j]:
            lst = list(s)
            lst[i], lst[j] = lst[j], lst[i]
            return float("".join(lst))
    return _money(gp * float(rng.choice([10, 0.1, 1.1, 0.9])))


def _reorder(lines: list[BidLine], rng: np.random.Generator) -> list[BidLine]:
    out = []
    for tr in sorted({ln.trade for ln in lines}):
        grp = [ln for ln in lines if ln.trade == tr]
        if len(grp) > 3:
            i, j = rng.choice(len(grp), size=2, replace=False)
            grp[int(i)], grp[int(j)] = grp[int(j)], grp[int(i)]
        out += grp
    return out


def _number(lines: list[BidLine], layout: dict[str, bool]) -> None:
    if layout["no_numbering"]:
        for ln in lines:
            ln.shown_no = ""
    elif layout["own_numbering"]:
        cur, k = None, 0
        t_idx = {tr: i + 1 for i, tr in enumerate(sorted({ln.trade for ln in lines}))}
        for ln in lines:
            if ln.trade != cur:
                cur, k = ln.trade, 0
            k += 1
            ln.shown_no = f"{t_idx[ln.trade]}.{k}"


def _abbreviate(text: str, abbr: dict[str, str]) -> str:
    for long_, short in sorted(abbr.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(long_, short, text)
        text = re.sub(long_.lower(), short, text)
    return text
