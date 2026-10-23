import hashlib
import io

import pytest
from fastapi.testclient import TestClient
from helpers import small_result
from reportlab.pdfgen import canvas

from ble.chat import Evidence, answer, verify
from ble.runs import export


@pytest.fixture(scope="module")
def run_dict(tmp_path_factory):
    return export(small_result(), tmp_path_factory.mktemp("runs"))


def test_verifier_drops_lines_citing_unknown_evidence():
    ev = Evidence()
    ref = ev.cite({"doc": "d@1", "text": "x"})
    text, dropped = verify(f"Supported {ref}\nInvented [E9]\nPlain line", ev)
    assert text == f"Supported {ref}\nPlain line" and dropped == 1


def test_ranking_cites_every_bidder(run_dict):
    a = answer(run_dict, "Who is cheapest?")
    assert a.intent == "ranking" and a.dropped == 0
    assert a.text.splitlines()[0].startswith("1. ") and len(a.citations) == 3


def test_findings_for_a_named_bidder(run_dict):
    a = answer(run_dict, "Where does Schulte deviate from the BoQ?")
    assert a.intent == "findings"
    assert "No price for 01.0010" in a.text and "31.12.2026" in a.text
    assert all(c.doc for c in a.citations)


def test_unknown_bidder_is_said_not_guessed(run_dict):
    a = answer(run_dict, "Where does Wagner Tiefbau deviate from the BoQ?")
    assert a.intent == "unknown_bidder" and "Schulte Bau GmbH" in a.text and a.citations == []


def test_prices_for_a_searched_position(run_dict):
    a = answer(run_dict, "Preise für die Stb.-Wand")
    assert a.intent == "prices" and a.text.startswith("03.0020")
    assert "Hoffmann Hochbau GmbH: 128.00 €" in a.text


@pytest.fixture()
def client(tmp_path, monkeypatch, run_dict):
    import json

    from ble.service import app as svc

    (tmp_path / "reports" / "runs").mkdir(parents=True)
    (tmp_path / "reports" / "runs" / "X01.json").write_text(json.dumps(run_dict, default=str))
    data = tmp_path / "data"
    (data / "X01").mkdir(parents=True)
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, "03.0020 Stahlbetonwand 410 m2 128,00 52.480,00")
    c.save()
    (data / "X01" / "a.pdf").write_bytes(buf.getvalue())
    monkeypatch.setattr(svc, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(svc, "DATA", data)
    monkeypatch.setattr(svc, "PLATFORM", "")
    svc._render.cache_clear()
    return TestClient(svc.app), hashlib.sha256(buf.getvalue()).hexdigest()[:12], data


def test_service_chat_and_search(client):
    c, _, _ = client
    assert c.get("/health").json()["ok"]
    r = c.post("/chat", json={"tender_id": "X01", "question": "Who is cheapest?"})
    assert r.status_code == 200 and r.json()["intent"] == "ranking"
    assert c.post("/chat", json={"tender_id": "../etc", "question": "hi there"}).status_code == 422
    assert c.post("/chat", json={"tender_id": "NOPE", "question": "hi there"}).status_code == 404
    hits = c.get("/search", params={"tender_id": "X01", "q": "Trittschalldämmung"}).json()
    assert hits[0]["oz"] == "04.0020"


def test_evidence_crop_checks_the_document_hash(client):
    c, sha, data = client
    r = c.get("/evidence.png", params={"doc": f"X01/a.pdf@{sha}", "page": 1, "bbox": "70,60,400,75"})
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert c.get("/evidence.png", params={"doc": "X01/a.pdf@000000000000"}).status_code == 409
    assert c.get("/evidence.png", params={"doc": f"../../etc/passwd@{sha}"}).status_code == 404
    (data / "X01" / "a.pdf").write_bytes(b"%PDF-1.4 changed")
    assert c.get("/evidence.png", params={"doc": f"X01/a.pdf@{sha}"}).status_code == 409
