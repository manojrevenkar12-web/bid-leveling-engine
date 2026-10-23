"""Small hand-built tenders and bids for unit tests (no simulator, no answer key)."""

from __future__ import annotations

from ble.ingest.model import BidDoc, BidLine, Evidence, Sentence, TenderDoc, TenderPosition

POSITIONS = [
    ("01.0010", "01", "Baustelle einrichten", "Baustelleneinrichtung vorhalten und räumen.", 1, "psch"),
    ("02.0010", "02", "Oberboden abtragen", "Oberboden abtragen, seitlich lagern, Dicke 30 cm.", 840, "m2"),
    ("02.0020", "02", "Baugrube ausheben", "Boden der Homogenbereich 2 lösen und laden.", 1250, "m3"),
    ("03.0010", "03", "Sauberkeitsschicht C8/10", "Sauberkeitsschicht aus Beton C8/10, Dicke 5 cm.", 288, "m2"),
    ("03.0020", "03", "Stahlbetonwand C30/37", "Wand aus Stahlbeton C30/37, Dicke 24 cm, Sichtbeton SB2.", 410, "m2"),
    ("03.0030", "03", "Betonstahl B500B", "Betonstahl B500B liefern, schneiden, biegen, verlegen.", 38, "t"),
    ("04.0010", "04", "Trockenbauwand EI 90", "Ständerwand, Feuerwiderstand EI 90, Leitfabrikat: Knauf W112 oder gleichwertig.", 520, "m2"),
    ("04.0020", "04", "Trittschalldämmung", "Trittschalldämmung, Dicke 30 mm, Steifigkeit 20 MN/m3.", 960, "m2"),
]


def tender(version: str = "v1", drop: tuple[str, ...] = (), qty: dict[str, float] | None = None, tid: str = "X01") -> TenderDoc:
    qty = qty or {}
    pos = [
        TenderPosition(oz, tr, sh, lo, qty.get(oz, q), u, Evidence(f"{tid}/tender/LV_{version}.x83@aaaaaaaaaaaa", xml_line=10 + i, text=sh))
        for i, (oz, tr, sh, lo, q, u) in enumerate(POSITIONS)
        if oz not in drop
    ]
    return TenderDoc(
        tid,
        version,
        "2026-09-01" if version == "v1" else "2026-09-15",
        f"LV {version}",
        "Neubau Kita Beispielstraße",
        {"01": "Baustelle", "02": "Erdarbeiten", "03": "Beton", "04": "Ausbau"},
        pos,
        f"{tid}/tender/LV_{version}.x83@aaaaaaaaaaaa",
    )


PRICES = {"01.0010": 18500.0, "02.0010": 4.8, "02.0020": 14.5, "03.0010": 14.2, "03.0020": 128.0, "03.0030": 1650.0, "04.0010": 74.0, "04.0020": 9.6}


def line(
    i: int,
    shown: str,
    short: str,
    qty: float | None,
    unit: str,
    ep: float | None,
    gp: float | None = None,
    long: str = "",
    trade: str = "",
    included: bool = False,
    product: str | None = None,
    conf: float = 1.0,
) -> BidLine:
    if gp is None and ep is not None and qty is not None:
        gp = round(ep * qty, 2)
    return BidLine(
        i,
        shown,
        trade,
        short,
        long,
        qty,
        unit,
        ep,
        gp,
        included,
        product,
        Evidence("X01/bids/B/angebot.pdf@bbbbbbbbbbbb", page=1, bbox=(40.0, 100.0 + 12 * i, 550.0, 110.0 + 12 * i), text=short),
        conf,
    )


def clean_bid(
    bid_id: str = "X01-B1",
    factor: float = 1.0,
    route: str = "pdf_text",
    boq: TenderDoc | None = None,
    company: str = "Schulte Bau GmbH",
    letter: list[str] | None = None,
) -> BidDoc:
    boq = boq or tender()
    lines = [line(i, p.oz, p.short, p.qty, p.unit, round(PRICES[p.oz] * factor, 2), long=p.long, trade=p.trade) for i, p in enumerate(boq.positions)]
    sents = [
        Sentence(t, Evidence("X01/bids/B/anschreiben.pdf@cccccccccccc", page=1, bbox=(40, 200 + 14 * i, 500, 210 + 14 * i), text=t))
        for i, t in enumerate(letter or [])
    ]
    return BidDoc(bid_id, boq.tender_id, company, route, lines, sents, None, "", ["X01/bids/B/angebot.pdf@bbbbbbbbbbbb"], 2, 0.0, 0.1)


def small_result(tid: str = "X01"):
    """A leveled three-bid tender, built through the harness like `level_tender` does."""
    from ble.deviate.detect import detect_bid, detect_tender
    from ble.deviate.level import level
    from ble.graph.build import build
    from ble.harness.trace import Run
    from ble.resolve.match import Matcher, resolve
    from ble.workflows import TenderResult

    v = [tender(tid=tid)]
    a = clean_bid(f"{tid}-B1", 0.97, company="Schulte Bau GmbH", letter=["Wir danken für Ihre Anfrage.", "Unsere Preise gelten nur bis zum 31.12.2026."])
    a.lines[0].ep = a.lines[0].gp = None
    b = clean_bid(f"{tid}-B2", 1.0, company="Hoffmann Hochbau GmbH")
    c = clean_bid(f"{tid}-B3", 1.02, company="Krüger & Partner Bauunternehmung")
    bids = [a, b, c]
    run = Run("bid-leveling")
    res = run.step("resolve_positions", lambda: [resolve(x, v, Matcher.default()) for x in bids])
    fs = run.step("detect_deviations", lambda: [f for x, r in zip(bids, res, strict=True) for f in detect_bid(x, r, v)] + detect_tender(bids, res, v))
    sheet = run.step("level_bids", level, v, bids, res, fs)
    graph = build(v, bids, res, fs, {"run_id": run.run_id}).as_dict()
    return TenderResult(tid, v, bids, res, fs, sheet, graph, run)
