import pytest

from ble.ingest.model import de_num
from ble.text.de import BM25, CONSTRUCTION, PLAIN, fold, split_compound, stem, unit


@pytest.mark.parametrize(
    "s,v",
    [
        ("1.234,56", 1234.56),
        ("12,5", 12.5),
        ("0,00", 0.0),
        ("1.250", 1250.0),
        ("-3,10", -3.1),
        ("410", 410.0),
        ("12.5", 12.5),
        ("€ 7,20", 7.2),
        ("", None),
        ("abc", None),
        ("12,3,4", None),
    ],
)
def test_de_num(s, v):
    assert de_num(s) == v


def test_fold_umlauts_and_digraphs():
    assert fold("Trittschalldämmung") == fold("Trittschalldaemmung") == "trittschalldammung"
    assert fold("Straße") == "strasse"


def test_compound_splitting():
    assert split_compound("stahlbetonwand") == ("stahl", "beton", "wand")
    assert split_compound("xyzqq") == ()


def test_stem():
    assert stem("fliesen") == "flies"
    assert stem("tur") == "tur"  # too short to stem


def test_abbreviations_meet_the_full_word():
    a, b = set(CONSTRUCTION.tokens("Stb.-Wand d=24 cm")), set(CONSTRUCTION.tokens("Stahlbetonwand"))
    assert {"stahl", "beton", "wand"} <= a & b
    assert not set(PLAIN.tokens("Stb.-Wand")) & set(PLAIN.tokens("Stahlbetonwand"))


def test_spec_codes_and_units():
    t = CONSTRUCTION.tokens("Beton C30/37, Tür EI 90, 24 m²")
    assert "s:c30/37" in t and "s:ei90" in t and "u:m2" in t
    assert unit("m²") == unit("qm") == "m2"
    assert unit("weird") == "weird"


def test_camel_case_shorthand():
    assert "sockel" in CONSTRUCTION.tokens("SockelFl.")


def test_bm25_ranks_the_compound_match_first():
    docs = ["Stahlbetonwand C30/37 Dicke 24 cm", "Mauerwerk Kalksandstein", "Trockenbauwand Gipskarton"]
    idx = BM25([CONSTRUCTION.tokens(d) for d in docs])
    assert idx.top(CONSTRUCTION.tokens("Stb. Wand"), 1)[0][0] == 0
    assert idx.top(CONSTRUCTION.tokens("nothing here at all qqq"), 3) == []
