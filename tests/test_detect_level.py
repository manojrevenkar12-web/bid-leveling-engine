from helpers import clean_bid, tender

from ble.deviate.detect import compare_spec, detect_bid, detect_tender, reservations
from ble.deviate.level import level
from ble.resolve.match import Matcher, resolve


def _run(bids, versions):
    res = [resolve(b, versions, Matcher.default()) for b in bids]
    fs = [f for b, r in zip(bids, res, strict=True) for f in detect_bid(b, r, versions)]
    fs += detect_tender(bids, res, versions)
    return res, fs


def _types(fs, bid_id=None):
    return sorted((f.type, f.oz) for f in fs if bid_id is None or f.bid_id == bid_id)


def test_spec_direction():
    assert compare_spec("Beton C30/37, Dicke 24 cm", "Beton C25/30, Dicke 24 cm")[0]["direction"] == "worse"
    assert compare_spec("Dicke 160 mm, Wärmeleitfähigkeit 0,035", "Dicke 160 mm, Wärmeleitfähigkeit 0,040")[0]["direction"] == "worse"
    assert compare_spec("Feuerwiderstand EI 90", "Feuerwiderstand EI 30")[0]["direction"] == "worse"
    assert compare_spec("Tür T30-RS", "Tür T90-RS")[0]["direction"] == "better"
    assert compare_spec("Dicke 160 mm", "Dicke 160 mm") == []


def test_clean_bids_have_no_findings():
    v = [tender()]
    _, fs = _run([clean_bid("X01-B1"), clean_bid("X01-B2", 1.05), clean_bid("X01-B3", 0.97)], v)
    assert fs == []


def test_line_rules():
    v = [tender()]
    b = clean_bid("X01-B1")
    L = {ln.shown_no: ln for ln in b.lines}
    L["01.0010"].ep = L["01.0010"].gp = None  # missing price
    L["02.0010"].included, L["02.0010"].ep, L["02.0010"].gp = True, 0.0, 0.0
    L["02.0020"].gp = 18000.0  # 14.50 x 1250 = 18125
    L["03.0010"].qty, L["03.0010"].gp = 250.0, 3550.0
    L["03.0030"].unit = "kg"
    L["03.0020"].long = "Wand aus Stahlbeton C25/30, Dicke 24 cm, Sichtbeton SB2."
    L["04.0010"].product = "Siniat Prowand 90"
    _, fs = _run([b], v)
    assert _types(fs) == [
        ("arithmetic_error", "02.0020"),
        ("included_price", "02.0010"),
        ("missing_price", "01.0010"),
        ("product_alternative", "04.0010"),
        ("qty_changed", "03.0010"),
        ("spec_change", "03.0020"),
        ("unit_changed", "03.0030"),
    ]
    spec = next(f for f in fs if f.type == "spec_change")
    assert spec.detail["direction"] == "worse" and spec.expected == "c30/37" and spec.found == "c25/30"
    assert all(f.evidence for f in fs)
    assert all(not f.needs_review for f in fs)  # a text PDF with clear matches is auto-confirmed


def test_same_product_is_not_an_alternative():
    b = clean_bid()
    b.lines[6].product = "Knauf W112 Metallständerwand"
    _, fs = _run([b], [tender()])
    assert fs == []


def test_outdated_version_and_missing_position():
    v1, v2 = tender("v1"), tender("v2", qty={"02.0020": 1480, "03.0020": 455})
    _, fs = _run([clean_bid(boq=v1)], [v1, v2])
    assert ("outdated_version", None) in _types(fs)


def test_reservations_from_cover_letter():
    b = clean_bid(
        letter=[
            "Wir danken für Ihre Anfrage.",
            "Unsere Preise gelten nur bis zum 31.12.2026.",
            "Die Entsorgung belasteter Böden ist nicht im Angebot enthalten.",
        ]
    )
    fs = reservations(b)
    assert [f.detail["kinds"][0] for f in fs] == ["price_validity", "scope_exclusion"]
    assert fs[0].evidence[0]["page"] == 1


def test_price_outlier_needs_three_bids():
    v = [tender()]
    hi = clean_bid("X01-B3")
    hi.lines[4].ep = 128.0 * 3.2
    hi.lines[4].gp = round(hi.lines[4].ep * hi.lines[4].qty, 2)
    _, fs = _run([clean_bid("X01-B1"), clean_bid("X01-B2", 1.04), hi], v)
    assert _types(fs) == [("price_outlier", "03.0020")]
    _, fs2 = _run([clean_bid("X01-B1"), hi], v)
    assert fs2 == []


def test_speculative_pricing():
    v = [tender()]
    spec = clean_bid("X01-B4")
    for ln in spec.lines:
        risky = ln.shown_no in ("02.0020", "03.0030")
        ln.ep = round(ln.ep * (2.1 if risky else 0.85), 2)
        ln.gp = round(ln.ep * ln.qty, 2)
    _, fs = _run([clean_bid("X01-B1"), clean_bid("X01-B2", 1.03), clean_bid("X01-B3", 0.98), spec], v)
    assert ("speculative_pricing", None) in _types(fs, "X01-B4")


def test_leveling_reprices_and_reranks():
    v = [tender()]
    a = clean_bid("X01-B1", 0.97, company="Alpha Bau GmbH")
    a.lines[4].ep = a.lines[4].gp = None  # the wall is not priced
    b = clean_bid("X01-B2", 1.0, company="Beta Bau GmbH")
    c = clean_bid("X01-B3", 1.0, company="Gamma Bau GmbH")
    c.lines[4].ep, c.lines[4].gp = 300.0, 123000.0
    res, fs = _run([a, b, c], v)
    s = level(v, [a, b, c], res, fs)
    cell = s.cells["03.0020"]["X01-B1"]
    assert cell.filled and cell.gp_comparable == 123000.0 and "missing_price" in cell.flags  # valued at the highest other price
    by = {x["bid_id"]: x for x in s.bidders}
    assert by["X01-B1"]["stated_total"] < by["X01-B2"]["stated_total"]
    assert [r["bid_id"] for r in s.ranking] == ["X01-B2", "X01-B1", "X01-B3"]
    assert s.ranking[0]["stated_rank"] == 2 and by["X01-B1"]["positions_valued_at_highest_other_price"] == 1


def test_reservations_span_dates_and_other_word_orders():
    b = clean_bid(
        letter=[
            "Dieses Angebot ist bis zum 15.11.2026 gültig.",
            "Abschlagsrechnungen sind innerhalb von 10 Tagen ohne Abzug zu zahlen.",
            "Unsere Haftung für Folgeschäden beschränken wir auf die Höhe der Auftragssumme.",
            "Sämtliche Positionen des Leistungsverzeichnisses sind bepreist.",
        ]
    )
    assert [f.detail["kinds"][0] for f in reservations(b)] == ["price_validity", "payment_terms", "liability"]
