"""Write tenders and bids the way they arrive: GAEB XML, PDFs printed by estimating software,
spreadsheets, and scans of printed, signed bids."""

from __future__ import annotations

import io
import time
import re
import zipfile
from datetime import datetime
from pathlib import Path

import numpy as np
from openpyxl import Workbook
from PIL import Image, ImageFilter
from reportlab import rl_config
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from ble import gaeb
from ble.config import WORLD
from ble.sim.tender import Bid, BoQ

rl_config.invariant = 1  # same input, same bytes: documents hash the same across runs
_FONTS = False


def _fonts() -> None:
    global _FONTS
    if not _FONTS:
        pdfmetrics.registerFont(TTFont("DejaVu", str(WORLD / "fonts" / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(WORLD / "fonts" / "DejaVuSans-Bold.ttf")))
        _FONTS = True


def de(x: float | None, decimals: int = 2) -> str:
    """German number format: 1.234,56"""
    if x is None:
        return ""
    s = f"{x:,.{decimals}f}"
    return s.replace(",", "_").replace(".", ",").replace("_", ".")


def boq_gaeb(boq: BoQ, date: str) -> str:
    items = [gaeb.GaebItem(p.oz, p.short, p.long, p.qty, p.unit) for p in boq.positions]
    label = f"Leistungsverzeichnis {boq.project}, Stand {date}" + (" (1. Nachtrag)" if boq.version == "v2" else "")
    return gaeb.write(83, boq.project, label, date, boq.trades, items)


def bid_gaeb(bid: Bid, boq: BoQ, date: str) -> str:
    items = []
    for ln in bid.lines:
        bt = {"Fabrikat": ln.product} if ln.product else {}
        items.append(gaeb.GaebItem(ln.shown_no, ln.short, ln.long or "", ln.qty, ln.unit, ln.ep, ln.gp, bt))
    label = f"Leistungsverzeichnis {boq.project}, Stand {date}" + (" (1. Nachtrag)" if boq.version == "v2" else "")
    return gaeb.write(84, boq.project, label, date, boq.trades, items, company=bid.company)


def _wrap(c: canvas.Canvas, text: str, font: str, size: float, width: float) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if c.stringWidth(t, font, size) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def letter_page(c: canvas.Canvas, bid: Bid, project: str, total: float, date: str) -> None:
    W, H = A4
    c.setFont("DejaVu-Bold", 13)
    c.drawString(56, H - 70, bid.company)
    c.setFont("DejaVu", 9)
    c.drawString(56, H - 86, "Musterstraße 1 · 10115 Berlin · Tel. 030 1234567")
    c.setFont("DejaVu", 10)
    y = H - 150
    for s in ["Generalunternehmer Bau GmbH", "Abteilung Einkauf", "Projektstraße 5", "10179 Berlin"]:
        c.drawString(56, y, s)
        y -= 14
    c.drawRightString(W - 56, H - 150, f"Berlin, {date}")
    y -= 30
    c.setFont("DejaVu-Bold", 11)
    c.drawString(56, y, f"Angebot zum Bauvorhaben: {project}")
    y -= 16
    c.setFont("DejaVu", 10)
    c.drawString(56, y, f"Angebotssumme netto: {de(total)} €")
    y -= 30
    c.drawString(56, y, "Sehr geehrte Damen und Herren,")
    y -= 20
    for para in bid.letter:
        for line in _wrap(c, para, "DejaVu", 10, W - 112):
            c.drawString(56, y, line)
            y -= 14
        y -= 6
    y -= 14
    c.drawString(56, y, "Mit freundlichen Grüßen")
    y -= 40
    c.drawString(56, y, bid.company)
    c.showPage()


def _total(bid: Bid) -> float:
    return round(sum(ln.gp or 0.0 for ln in bid.lines), 2)


def bid_pdf(bid: Bid, boq: BoQ, date: str, with_letter: bool, qty_decimals: int = 3) -> bytes:
    _fonts()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Angebot {bid.company}")
    W, H = A4
    if with_letter:
        letter_page(c, bid, boq.project, _total(bid), date)
    X = {"no": 40, "text": 92, "qty": 412, "unit": 418, "ep": 498, "gp": 556}
    page = 0

    def header() -> float:
        nonlocal page
        page += 1
        c.setFont("DejaVu-Bold", 10)
        c.drawString(40, H - 40, f"Angebot {bid.company}")
        c.setFont("DejaVu", 8)
        c.drawString(40, H - 52, f"Bauvorhaben: {boq.project}")
        c.drawRightString(W - 40, H - 40, f"Seite {page}")
        c.setFont("DejaVu-Bold", 8)
        y = H - 76
        c.drawString(X["no"], y, "Pos.")
        c.drawString(X["text"], y, "Bezeichnung")
        c.drawRightString(X["qty"], y, "Menge")
        c.drawString(X["unit"], y, "ME")
        c.drawRightString(X["ep"], y, "EP €")
        c.drawRightString(X["gp"], y, "GP €")
        c.line(40, y - 4, W - 40, y - 4)
        return y - 16

    y = header()
    for tr in sorted({ln.trade for ln in bid.lines}, key=lambda t: [ln.trade for ln in bid.lines].index(t)):
        need = 30
        if y < 80 + need:
            c.showPage()
            y = header()
        c.setFont("DejaVu-Bold", 9)
        c.drawString(X["no"], y, f"Titel {tr}  {boq.trades.get(tr, '')}")
        y -= 16
        for ln in [x for x in bid.lines if x.trade == tr]:
            long_lines = _wrap(c, ln.long, "DejaVu", 7, 300) if ln.long else []
            block = 12 + 9 * len(long_lines) + (10 if ln.product else 0) + 4
            if y - block < 70:
                c.showPage()
                y = header()
            c.setFont("DejaVu", 8.5)
            c.drawString(X["no"], y, ln.shown_no)
            c.drawString(X["text"], y, ln.short[:70])
            c.drawRightString(X["qty"], y, de(ln.qty, qty_decimals))
            c.drawString(X["unit"], y, ln.unit)
            c.drawRightString(X["ep"], y, "enthalten" if ln.included else de(ln.ep))
            c.drawRightString(X["gp"], y, "" if ln.included else de(ln.gp))
            y -= 11
            c.setFont("DejaVu", 7)
            for t in long_lines:
                c.drawString(X["text"], y, t)
                y -= 9
            if ln.product:
                c.drawString(X["text"], y, f"Angebotenes Fabrikat: {ln.product}")
                y -= 10
            y -= 4
        c.setFont("DejaVu-Bold", 8.5)
        c.drawString(X["text"], y, f"Summe Titel {tr}")
        c.drawRightString(X["gp"], y, de(sum(x.gp or 0 for x in bid.lines if x.trade == tr)))
        y -= 20
    if y < 120:
        c.showPage()
        y = header()
    total = _total(bid)
    c.setFont("DejaVu-Bold", 9)
    for lbl, v in (("Angebotssumme netto", total), ("zzgl. 19 % MwSt.", total * 0.19), ("Angebotssumme brutto", total * 1.19)):
        c.drawString(X["text"], y, lbl)
        c.drawRightString(X["gp"], y, de(v))
        y -= 13
    c.showPage()
    c.save()
    return buf.getvalue()


def letter_pdf(bid: Bid, project: str, date: str) -> bytes:
    _fonts()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    letter_page(c, bid, project, _total(bid), date)
    c.save()
    return buf.getvalue()


HEADERS = [
    ["OZ", "Kurztext", "Menge", "Einheit", "EP", "GP"],
    ["Pos.", "Bezeichnung", "Menge", "ME", "EP (€)", "GP (€)"],
    ["Position", "Leistung", "Menge", "ME", "Einheitspreis", "Gesamtpreis"],
    ["Nr.", "Text", "Anzahl", "Einh.", "EP netto", "GP netto"],
]


def bid_xlsx(bid: Bid, boq: BoQ, rng: np.random.Generator) -> bytes:
    wb = Workbook()
    wb.properties.created = wb.properties.modified = datetime(2026, 9, 28, 9, 0, 0)
    ws = wb.active
    ws.title = "LV"
    hdr = HEADERS[int(rng.integers(len(HEADERS)))]
    with_product = any(ln.product for ln in bid.lines)
    ws.append([f"Angebot {bid.company} – {boq.project}"])
    ws.append([])
    ws.append(hdr + (["Fabrikat"] if with_product else []))
    for tr in sorted({ln.trade for ln in bid.lines}, key=lambda t: [ln.trade for ln in bid.lines].index(t)):
        ws.append([tr, boq.trades.get(tr, "")])
        for ln in [x for x in bid.lines if x.trade == tr]:
            ep = "enthalten" if ln.included else ln.ep
            gp = None if ln.included else ln.gp
            row = [ln.shown_no, ln.short, ln.qty, ln.unit, ep, gp]
            if with_product:
                row.append(ln.product or "")
            ws.append(row)
        ws.append(["", f"Summe Titel {tr}", None, None, None, round(sum(x.gp or 0 for x in bid.lines if x.trade == tr), 2)])
    ws.append([])
    ws.append(["", "Angebotssumme netto", None, None, None, _total(bid)])
    buf = io.BytesIO()
    wb.save(buf)
    return _stable_zip(buf.getvalue())


def _stable_zip(data: bytes) -> bytes:
    """Re-pack a zip (xlsx) with fixed timestamps so the same bid always has the same hash."""
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for info in src.infolist():
            zi = zipfile.ZipInfo(info.filename, date_time=(2026, 9, 28, 9, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            body = src.read(info.filename)
            if info.filename == "docProps/core.xml":
                body = re.sub(rb"(<dcterms:modified[^>]*>)[^<]*", rb"\g<1>2026-09-28T09:00:00Z", body)
            z.writestr(zi, body)
    return out.getvalue()


def scan(pdf: bytes, rng: np.random.Generator, dpi: int = 160) -> bytes:
    """Print, sign and scan: pages become slightly rotated, noisy grey images without a text layer."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf)
    pages = []
    for i in range(len(doc)):
        img = doc[i].render(scale=dpi / 72).to_pil().convert("L")
        img = img.rotate(float(rng.uniform(-0.7, 0.7)), resample=Image.Resampling.BICUBIC, expand=False, fillcolor=255)
        arr = np.asarray(img, dtype=np.float32)
        arr = arr * float(rng.uniform(0.9, 1.0)) + rng.normal(0, 9, arr.shape)
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius=float(rng.uniform(0.2, 0.5))))
        pages.append(img)
    buf = io.BytesIO()
    fixed = time.strptime("2026-09-28 09:00:00", "%Y-%m-%d %H:%M:%S")
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:], resolution=dpi, creationDate=fixed, modDate=fixed)
    return buf.getvalue()


def write_bytes(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
