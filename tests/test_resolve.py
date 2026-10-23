import numpy as np
from helpers import POSITIONS, PRICES, clean_bid, line, tender

from ble.resolve.match import Matcher, assign, baseline_oz_only, resolve


def test_assign_allows_no_position():
    P = np.array([[0.95, 0.10], [0.05, 0.08], [0.20, 0.90]])
    assert assign(P, p_none=0.3) == [0, -1, 1]


def test_clean_bid_matches_by_number_and_text():
    r = resolve(clean_bid(), [tender()], Matcher.default())
    assert [m.oz for m in r.matches] == [p[0] for p in POSITIONS]
    assert r.unmatched_positions == []


def test_renumbered_abbreviated_reordered_bid_still_matches():
    boq = tender()
    short = {"03.0020": "Stb.-Wand C30/37 d=24cm", "04.0020": "TSD 30mm", "02.0020": "Aushub Baugrube"}
    order = list(reversed(boq.positions))
    lines = [line(i, f"{i + 1}", short.get(p.oz, p.short), p.qty, p.unit, PRICES[p.oz]) for i, p in enumerate(order)]
    bid = clean_bid()
    bid.lines = lines
    r = resolve(bid, [boq], Matcher.default())
    assert [m.oz for m in r.matches] == [p.oz for p in order]
    assert baseline_oz_only(bid, boq) == [None] * len(lines)  # the position numbers alone find nothing


def test_added_line_and_missing_position():
    boq = tender()
    bid = clean_bid()
    bid.lines = [ln for ln in bid.lines if ln.shown_no != "02.0010"]
    bid.lines.append(line(len(bid.lines), "", "Winterbaumaßnahmen Beheizung Rohbau", 1, "psch", 6400.0))
    for i, ln in enumerate(bid.lines):
        ln.idx = i
    r = resolve(bid, [boq], Matcher.default())
    assert r.matches[-1].oz is None
    assert r.unmatched_positions == ["02.0010"]


def test_version_is_chosen_by_quantities():
    v1 = tender("v1")
    v2 = tender("v2", drop=("04.0020",), qty={"02.0020": 1480, "03.0020": 455})
    old = clean_bid(boq=v1)
    new = clean_bid(boq=v2)
    assert resolve(old, [v1, v2], Matcher.default()).version == "v1"
    assert resolve(new, [v1, v2], Matcher.default()).version == "v2"


def test_low_ocr_confidence_goes_to_review():
    bid = clean_bid(route="ocr")
    bid.lines[3].confidence = 0.4
    r = resolve(bid, [tender()], Matcher.default())
    assert r.matches[3].needs_review and not r.matches[2].needs_review


def test_matcher_save_load(tmp_path):
    m = Matcher([1.0] * 9, -2.0, {"source": "test"})
    m.save(tmp_path / "m.json")
    assert Matcher.load(tmp_path / "m.json") == m
    assert Matcher.load(tmp_path / "missing.json").trained_on["source"] == "default"


def test_position_numbers_compare_by_value():
    from ble.resolve.match import same_oz, units_compatible

    assert same_oz("3.10", "03.0010") and same_oz("03.0010", "03.0010") and not same_oz("1.1", "01.0010") and not same_oz("", "01.0010")
    assert units_compatible("qm", "m2") and units_compatible("m?", "m3") and not units_compatible("m?", "St") and not units_compatible("t", "kg")


def test_second_pass_pairs_a_line_by_quantity_and_neighbours():
    boq = tender()
    bid = clean_bid()
    for ln in bid.lines:
        ln.shown_no = ""
    bid.lines[4].short = "Wandscheibe Ortbeton"  # 03.0020 described in words the BoQ does not use
    bid.lines[4].long = ""
    r = resolve(bid, [boq], Matcher.default())
    assert r.matches[4].oz == "03.0020" and r.matches[4].needs_review
    assert r.unmatched_positions == []
