from helpers import line

from ble.ingest.repair import repair
from ble.ingest.table import Word, letter_sentences, lines_of, parse_table


def _row(page, top, cells):
    return [Word(t, x0, x1, top, top + 9, page) for t, x0, x1 in cells]


HEADER = [
    ("OZ", 40, 55),
    ("Bezeichnung", 100, 160),
    ("Menge", 330, 360),
    ("ME", 370, 385),
    ("EP", 440, 455),
    ("€", 457, 462),
    ("GP", 520, 535),
    ("€", 537, 542),
]


def _doc():
    w = _row(1, 60, [("Bauunternehmung", 40, 120), ("Beispiel", 125, 170)])
    w += _row(1, 100, HEADER)
    w += _row(1, 115, [("Titel", 40, 60), ("03", 62, 72), ("Beton", 100, 130)])
    w += _row(
        1,
        130,
        [
            ("03.0010", 40, 80),
            ("Sauberkeitsschicht", 100, 180),
            ("C8/10", 182, 205),
            ("288,000", 320, 360),
            ("m2", 370, 382),
            ("14,20", 430, 462),
            ("4.089,60", 500, 542),
        ],
    )
    w += _row(1, 142, [("Beton", 100, 125), ("Dicke", 127, 150), ("5", 152, 156), ("cm", 158, 168)])
    w += _row(1, 160, [("03.0020", 40, 80), ("Stb.-Wand", 100, 150), ("410,000", 320, 360), ("m2", 370, 382), ("enthalten", 420, 462)])
    w += _row(1, 175, [("Angebotenes", 100, 150), ("Fabrikat:", 152, 190), ("Knauf", 192, 215), ("W112", 217, 240)])
    w += _row(1, 200, [("Angebotssumme", 100, 170), ("netto", 172, 195), ("4.089,60", 500, 542)])
    return w


def test_parse_table_reads_items_long_text_products_and_total():
    lines, total, warnings = parse_table(_doc(), "T/b.pdf@x")
    assert warnings == []
    assert total == 4089.60
    assert [ln.shown_no for ln in lines] == ["03.0010", "03.0020"]
    a, b = lines
    assert (a.qty, a.unit, a.ep, a.gp, a.trade_hint) == (288.0, "m2", 14.2, 4089.6, "03")
    assert a.long == "Beton Dicke 5 cm"
    assert b.included and b.product == "Knauf W112"
    assert a.evidence.page == 1 and a.evidence.bbox is not None


def test_no_header_is_a_warning():
    _, _, warnings = parse_table(_row(1, 100, [("hello", 40, 60)]), "d")
    assert warnings == ["no table header found"]


def test_lines_of_groups_slightly_rotated_words():
    words = [Word("a", 10, 20, 100, 110, 1), Word("b", 30, 40, 101.5, 111.5, 1), Word("c", 10, 20, 130, 140, 1)]
    assert [[w.text for w in ln] for ln in lines_of(words)] == [["a", "b"], ["c"]]


def test_letter_sentences_keep_abbreviations_and_dates():
    w = _row(1, 100, [("Sehr", 40, 60), ("geehrte", 62, 100), ("Damen", 102, 130)])
    w += _row(
        1,
        120,
        [
            ("Die", 40, 55),
            ("Preise", 57, 85),
            ("gelten", 87, 115),
            ("bis", 117, 130),
            ("30.11.", 132, 150),
            ("z.", 152, 160),
            ("B.", 162, 170),
            ("netto.", 172, 200),
        ],
    )
    w += _row(1, 135, [("Angebotssumme", 40, 100), ("netto:", 102, 130), ("12.500,00", 132, 180), ("EUR.", 182, 200)])
    w += _row(1, 150, [("Mit", 40, 55), ("freundlichen", 57, 110)])
    s, total = letter_sentences(w, "d")
    assert total == 12500.0
    assert s[0].text == "Die Preise gelten bis 30.11. z. B. netto."
    assert len(s) == 2


def test_repair_fixes_one_glyph_and_leaves_real_errors():
    ocr = line(0, "1", "x", 288.0, "m2", 14.70, 4089.60)  # OCR read 14,20 as 14,70
    real = line(1, "2", "y", 100.0, "m2", 12.34, 1243.00)  # transposed digits: a real error
    derived = line(2, "3", "z", 10.0, "St", None, 125.0)
    n = repair([ocr, real, derived])
    assert ocr.ep == 14.20 and ocr.confidence <= 0.75
    assert real.ep == 12.34 and real.gp == 1243.00
    assert derived.ep == 12.5
    assert n == 2


def test_ocr_units_without_superscript_and_l_misread():
    from ble.ingest.table import _unit_token

    assert _unit_token("m?") == "m?" and _unit_token("m*") == "m?"
    assert _unit_token("Ifdm") == "lfdm" and _unit_token("cbm") == "cbm" and _unit_token("Stck.") == "Stck"
    assert _unit_token("Wand") is None
