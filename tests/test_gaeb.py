import pytest
from lxml import etree

from ble import gaeb
from ble.gaeb import GaebItem


def test_write_read_roundtrip():
    items = [
        GaebItem("01.0010", "Baustelle einrichten", "Einrichten & räumen <inkl. WC>", 1.0, "psch", 18500.0, 18500.0),
        GaebItem("03.0020", "Stahlbetonwand C30/37", "Wand, Dicke 24 cm", 410.5, "m2", 128.0, 52544.0, {"Fabrikat": "Knauf W112"}),
        GaebItem("03.0030", "Betonstahl", "B500B", None, "t"),
    ]
    xml = gaeb.write(84, "Kita Süd", "LV v2", "2026-09-15", {"01": "Baustelle", "03": "Beton"}, items, company="Müller & Söhne GmbH")
    d = gaeb.read(xml.encode())
    assert d.dp == 84 and d.project == "Kita Süd" and d.boq_label == "LV v2" and d.boq_date == "2026-09-15"
    assert d.company == "Müller & Söhne GmbH"
    assert d.categories == {"01": "Baustelle", "03": "Beton"}
    got = {i.oz: i for i in d.items}
    assert set(got) == {"01.0010", "03.0020", "03.0030"}
    assert got["01.0010"].long == "Einrichten & räumen <inkl. WC>"
    assert got["03.0020"].qty == 410.5 and got["03.0020"].up == 128.0 and got["03.0020"].it == 52544.0
    assert got["03.0020"].bidder_texts == {"Fabrikat": "Knauf W112"}
    assert got["03.0030"].qty is None and got["03.0030"].up is None
    assert all(i.line > 0 for i in d.items)  # evidence links point at the XML line


def test_tender_phase_namespace():
    xml = gaeb.write(83, "P", "LV", "2026-09-01", {}, [GaebItem("01.0010", "a", "b", 1, "St")])
    assert "DA83/3.3" in xml
    assert gaeb.read(xml.encode()).dp == 83


def test_external_entities_are_not_resolved(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET")
    xml = f"""<?xml version="1.0"?><!DOCTYPE g [<!ENTITY x SYSTEM "file://{secret}">]>
<GAEB><PrjInfo><NamePrj>&x;</NamePrj></PrjInfo><Award><DP>84</DP></Award></GAEB>"""
    try:
        d = gaeb.read(xml.encode())
    except etree.XMLSyntaxError:
        return
    assert "TOPSECRET" not in d.project


def test_bad_xml_raises():
    with pytest.raises(etree.XMLSyntaxError):
        gaeb.read(b"<GAEB><unclosed></GAEB>")
