"""The AI service: evidence-linked chat, position search, evidence crops and workflow runs.

The platform API (platform/, TypeScript) is the system of record; this service reads runs from it
(or from reports/runs when it runs alone) and renders evidence straight from the source document,
after checking the document still has the hash the finding was made from.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from functools import lru_cache
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ble.chat import answer
from ble.config import DATA, REPORTS
from ble.service.client import fetch_run, publish
from ble.text.de import BM25, CONSTRUCTION

app = FastAPI(title="bid-leveling-engine AI service", version="0.1.0")
PLATFORM = os.environ.get("BLE_PLATFORM_URL", "")


def _run(tender_id: str) -> dict[str, Any]:
    if PLATFORM:
        try:
            return fetch_run(tender_id, PLATFORM)
        except Exception as e:  # fall back to local reports when the platform does not have it
            if not (REPORTS / "runs" / f"{tender_id}.json").exists():
                raise HTTPException(404, f"no run for {tender_id}: {e}") from e
    p = REPORTS / "runs" / f"{tender_id}.json"
    if not p.exists():
        raise HTTPException(404, f"no run for {tender_id}")
    return json.loads(p.read_text(encoding="utf-8"))


class ChatIn(BaseModel):
    tender_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    question: str = Field(min_length=2, max_length=500)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "platform": PLATFORM or None}


@app.post("/chat")
def chat(body: ChatIn) -> dict[str, Any]:
    return answer(_run(body.tender_id), body.question).as_dict()


@app.get("/search")
def search(tender_id: str, q: str = Query(min_length=2, max_length=200), k: int = 5) -> list[dict[str, Any]]:
    pos = _run(tender_id)["versions"][-1]["positions"]
    idx = BM25([CONSTRUCTION.tokens(p["short"]) * 2 + CONSTRUCTION.tokens(p["long"]) for p in pos])
    return [{"oz": pos[i]["oz"], "short": pos[i]["short"], "score": round(s, 3)} for i, s in idx.top(CONSTRUCTION.tokens(q), k)]


@lru_cache(maxsize=256)
def _render(path: str, page: int, sha: str) -> bytes:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(path)
    img = doc[page - 1].render(scale=2).to_pil()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@app.get("/evidence.png")
def evidence(doc: str, page: int = 1, bbox: str | None = None, pad: float = 18.0) -> Response:
    """A crop of the page an evidence link points at, highlighted. 409 if the document changed."""
    rel, _, sha = doc.partition("@")
    path = (DATA / rel).resolve()
    if not str(path).startswith(str(DATA.resolve())) or not path.exists() or path.suffix.lower() != ".pdf":
        raise HTTPException(404, "no such document")
    if hashlib.sha256(path.read_bytes()).hexdigest()[:12] != sha:
        raise HTTPException(409, "the document changed since this finding was made")
    from PIL import Image, ImageDraw

    img = Image.open(io.BytesIO(_render(str(path), page, sha))).convert("RGB")
    s = 2.0
    if bbox:
        x0, t, x1, b = (float(v) for v in bbox.split(","))
        d = ImageDraw.Draw(img, "RGBA")
        d.rectangle([x0 * s - 3, t * s - 3, x1 * s + 3, b * s + 3], fill=(255, 196, 0, 70), outline=(214, 110, 0, 255), width=3)
        img = img.crop((0, max(0, int((t - 6 * pad) * s)), img.width, min(img.height, int((b + 6 * pad) * s))))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png")


class LevelIn(BaseModel):
    tender_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    publish: bool = True


@app.post("/level")
def level(body: LevelIn) -> dict[str, Any]:
    from ble.pipeline import export
    from ble.workflows import level_tender

    tdir = DATA / "tenders" / body.tender_id
    if not tdir.is_dir():
        raise HTTPException(404, "no such tender")
    r = level_tender(tdir)
    d = export(r, REPORTS / "runs")
    out = {"tender_id": body.tender_id, "run_id": d["run_id"], "findings": len(d["findings"]), "published": False}
    if body.publish and PLATFORM:
        out["published"] = publish(REPORTS / "runs" / f"{body.tender_id}.json", PLATFORM)
    return out
