"""Use the arithmetic a priced line must satisfy (unit price x quantity = total) to correct digits
OCR commonly confuses. A line is only changed when exactly one single-glyph correction of one
field makes it add up; real calculation errors (transposed digits, a misplaced decimal point) are
not reachable that way and stay visible."""

from __future__ import annotations

from ble.ingest.model import BidLine

CONFUSE = {"1": "74", "7": "12", "4": "19", "3": "85", "8": "3609", "5": "63", "6": "58", "0": "869", "9": "084", "2": "7"}


def _variants(x: float, decimals: int) -> list[float]:
    s = f"{x:.{decimals}f}"
    out = []
    for i, c in enumerate(s):
        for r in CONFUSE.get(c, ""):
            out.append(float(s[:i] + r + s[i + 1 :]))
    return out


def _ok(ep: float, qty: float, gp: float) -> bool:
    return abs(round(ep * qty, 2) - gp) <= max(0.02, 0.0005 * abs(gp))


def repair(lines: list[BidLine]) -> int:
    """Correct OCR'd lines in place; returns how many were changed."""
    n = 0
    for ln in lines:
        if ln.included or ln.qty is None:
            continue
        if ln.ep is None and ln.gp is not None and ln.qty:
            ln.ep = round(ln.gp / ln.qty, 2)
            ln.confidence = min(ln.confidence, 0.7)
            n += 1
            continue
        if ln.ep is None or ln.gp is None or _ok(ln.ep, ln.qty, ln.gp):
            continue
        cands = [("ep", v) for v in _variants(ln.ep, 2) if _ok(v, ln.qty, ln.gp)]
        cands += [("qty", v) for v in _variants(ln.qty, 3) if v and _ok(ln.ep, v, ln.gp)]
        cands += [("gp", v) for v in _variants(ln.gp, 2) if _ok(ln.ep, ln.qty, v)]
        if len(cands) == 1:
            f, v = cands[0]
            setattr(ln, f, v)
            ln.confidence = min(ln.confidence, 0.75)
            n += 1
    return n
