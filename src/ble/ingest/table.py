"""Turn positioned words (from a PDF text layer or OCR) into bid lines and letter sentences.

Estimating software prints a BoQ as a table: position number, text, quantity, unit, unit price,
total. The column header row gives the anchors; numbers are right-aligned under them. Titles,
subtotals, long-text lines and "offered product" lines are recognised by position and wording.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ble.ingest.model import BidLine, Evidence, Sentence, de_num


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    page: int
    conf: float = 100.0


TEXT_HDR = {"bezeichnung", "leistung", "kurztext", "text", "leistungsbeschreibung"}
QTY_HDR = {"menge", "anzahl"}
EP_HDR = {"ep", "einheitspreis", "ep€"}
GP_HDR = {"gp", "gesamtpreis", "gp€"}
UNIT_HDR = {"me", "einheit", "einh."}
UNITS = {"m", "m2", "m²", "m3", "m³", "st", "stk", "psch", "pauschal", "t", "kg", "h", "std", "wo", "tag", "lfm", "qm"}
ABBR_END = {"z.", "b.", "inkl.", "zzgl.", "ca.", "evtl.", "ggf.", "bzw.", "nr.", "str.", "abs.", "gem.", "lt.", "u.", "d."}


def lines_of(words: list[Word], tol: float = 3.0) -> list[list[Word]]:
    """Group words into text lines. A word joins the line whose last word is closest in height,
    so slightly rotated scans still give whole lines."""
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w.page, w.x0)):
        cy = (w.top + w.bottom) / 2
        best, best_d = None, None
        for ln in lines:
            last = ln[-1]
            if last.page != w.page or last.x1 > w.x0 + 1:
                continue
            d = abs((last.top + last.bottom) / 2 - cy)
            if d <= tol and (best_d is None or d < best_d):
                best, best_d = ln, d
        if best is None:
            lines.append([w])
        else:
            best.append(w)
    return sorted(lines, key=lambda ln: (ln[0].page, min(x.top for x in ln)))


@dataclass
class Anchors:
    text_left: float
    qty_right: float
    unit_left: float
    ep_right: float
    gp_right: float


def _norm(t: str) -> str:
    return t.lower().strip(":.()").replace("€", "") or t.lower()


def find_anchors(line: list[Word]) -> Anchors | None:
    toks = [_norm(w.text) for w in line]
    if not (TEXT_HDR & set(toks) and QTY_HDR & set(toks) and (EP_HDR & set(toks) or "einheitspreis" in toks)):
        return None
    get = lambda names: next((w for w, t in zip(line, toks, strict=True) if t in names), None)  # noqa: E731
    tw, qw, uw, ew, gw = get(TEXT_HDR), get(QTY_HDR), get(UNIT_HDR), get(EP_HDR), get(GP_HDR)
    if not (tw and qw and ew):
        return None

    # "EP €" / "GP €": the column's right edge is the last token of the label
    def right(w: Word) -> float:
        i = line.index(w)
        return line[i + 1].x1 if i + 1 < len(line) and line[i + 1].text.strip() in ("€", "(€)", "netto") else w.x1

    # an OCR'd header can lose its last label (rotated scans push it onto its own line); the total
    # column is then everything right of the unit price column
    return Anchors(tw.x0, qw.x1, uw.x0 if uw else qw.x1 + 4, right(ew), right(gw) if gw else float("inf"))


def _near(x: float, anchor: float, tol: float) -> bool:
    return abs(x - anchor) <= tol


MONEY = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}")


def _split_merged(ln: list[Word], a: Anchors) -> list[Word]:
    """OCR sometimes reads a unit price and a total as one token ("5,23::10.297,87"); split it."""
    out = []
    for w in ln:
        if de_num(w.text) is None and w.x0 < a.ep_right and w.x1 > a.ep_right:
            nums = MONEY.findall(re.sub(r"[:;]+", ".", w.text))
            if len(nums) == 2:
                out += [Word(nums[0], w.x0, a.ep_right, w.top, w.bottom, w.page, w.conf), Word(nums[1], a.ep_right + 4, w.x1, w.top, w.bottom, w.page, w.conf)]
                continue
        out.append(w)
    return out


def parse_table(words: list[Word], doc_id: str, scale_tol: float = 1.0) -> tuple[list[BidLine], float | None, list[str]]:
    """Bid lines, the stated net total, and warnings."""
    lines = lines_of(words, tol=3.0 * scale_tol)
    anchors: Anchors | None = None
    out: list[BidLine] = []
    trade = ""
    total: float | None = None
    warnings: list[str] = []
    in_table_page = -1
    for ln in lines:
        a = find_anchors(ln)
        if a:
            anchors, in_table_page = a, ln[0].page
            continue
        if anchors is None:
            continue
        if ln[0].page != in_table_page:
            # a page whose header row was not read (OCR) keeps the previous page's columns,
            # but its own running header (bidder name, project, page number) is skipped
            if ln[0].top < 80:
                continue
            in_table_page = ln[0].page
        T = 22 * scale_tol
        ln = _split_merged(ln, anchors)
        no = [w for w in ln if w.x1 < anchors.text_left - 2]

        def is_cell(w: Word) -> bool:
            t = w.text.strip().lower().strip(".")
            return de_num(w.text) is not None or t in UNITS or t in ("enthalten", "enth", "inkl")

        nums = [w for w in ln if w.x0 >= anchors.qty_right - 70 and w not in no and is_cell(w)]
        text = [w for w in ln if w not in no and w not in nums]
        txt = " ".join(w.text for w in text).strip()
        no_txt = " ".join(w.text for w in no).strip()
        low = (no_txt + " " + txt).lower().strip()
        bbox = (min(w.x0 for w in ln), min(w.top for w in ln), max(w.x1 for w in ln), max(w.bottom for w in ln))
        ev = Evidence(doc_id, page=ln[0].page, bbox=tuple(round(v, 1) for v in bbox), text=" ".join(w.text for w in ln))  # type: ignore[arg-type]
        conf = min(w.conf for w in ln) / 100.0
        m = re.match(r"^titel\s+(\d{1,2})\b", low)
        if m:
            trade = m.group(1).zfill(2)
            continue
        if low.startswith("summe titel") or low.startswith("zzgl") or "angebotssumme brutto" in low:
            continue
        if "angebotssumme netto" in low:
            vals = [de_num(w.text) for w in nums]
            vals = [v for v in vals if v is not None]
            total = vals[-1] if vals else total
            continue
        qty = ep = gp = None
        unit = ""
        included = False
        for w in nums:
            t = w.text.strip()
            if t.lower().strip(".") in ("enthalten", "enth", "incl", "inkl"):
                included = True
                continue
            v = de_num(t)
            if v is not None:
                if _near(w.x1, anchors.qty_right, T):
                    qty = v
                elif _near(w.x1, anchors.ep_right, T):
                    ep = v
                elif _near(w.x1, anchors.gp_right, T) or (anchors.gp_right == float("inf") and w.x1 > anchors.ep_right + T):
                    gp = v
                continue
            if t.lower() in UNITS and w.x0 >= anchors.unit_left - T:
                unit = t
        is_item = bool(unit) and (qty is not None or ep is not None or gp is not None or included)
        if is_item:
            out.append(BidLine(len(out), no_txt, trade, txt, "", qty, unit, ep, gp, included or (ep == 0 and gp == 0), None, ev, round(conf, 3)))
            continue
        if not out or not (txt or nums):
            continue
        mp = re.match(r"^angebotenes\s+fabrikat\s*:?\s*(.+)$", txt, re.I)
        if mp:
            out[-1].product = mp.group(1).strip()
            continue
        if not no_txt:  # long text under the last item (numbers in it are part of the text)
            full = " ".join(w.text for w in ln if w not in no).strip()
            out[-1].long = (out[-1].long + " " + full).strip()
    if anchors is None:
        warnings.append("no table header found")
    return out, total, warnings


def letter_sentences(words: list[Word], doc_id: str) -> tuple[list[Sentence], float | None]:
    """Sentences between the salutation and the closing, each with the box of its first line."""
    lines = lines_of(words)
    body: list[tuple[str, Evidence]] = []
    on, total = False, None
    for ln in lines:
        t = " ".join(w.text for w in ln)
        m = re.search(r"angebotssumme\s+netto:?\s*([\d.,]+)", t, re.I)
        if m:
            total = de_num(m.group(1))
        if re.match(r"^sehr geehrte", t, re.I):
            on = True
            continue
        if re.match(r"^mit freundlichen", t, re.I):
            break
        if on:
            bbox = (min(w.x0 for w in ln), min(w.top for w in ln), max(w.x1 for w in ln), max(w.bottom for w in ln))
            body.append((t, Evidence(doc_id, page=ln[0].page, bbox=tuple(round(v, 1) for v in bbox), text=t)))  # type: ignore[arg-type]
    sentences: list[Sentence] = []
    cur, cur_ev = "", None
    for t, ev in body:
        for tok in t.split():
            if not cur:
                cur_ev = ev
            cur = (cur + " " + tok).strip()
            if (
                tok.endswith((".", "!", "?"))
                and tok.lower() not in ABBR_END
                and not re.match(r"^\d{1,2}\.$", tok)
                and not re.match(r"^\d{1,2}\.\d{1,2}\.$", tok)
            ):
                sentences.append(Sentence(cur, Evidence(cur_ev.doc, cur_ev.page, cur_ev.bbox, text=cur)))  # type: ignore[union-attr]
                cur = ""
    if cur and cur_ev:
        sentences.append(Sentence(cur, Evidence(cur_ev.doc, cur_ev.page, cur_ev.bbox, text=cur)))
    return sentences, total
