"""A German tokenizer for construction texts.

German writes building parts as compounds (Stahlbetonwand, Trittschalldämmung,
Brandschutz-Ständerwand), estimators abbreviate them (Stb.-Wand, TSD), and OCR drops umlauts.
Plain word tokens miss all three. This tokenizer folds umlauts, expands shorthand, splits compounds
into known parts (keeping the whole word as well), and canonicalises units, so the same building
part meets itself across a BoQ, a bid and a search box.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import cache

from ble.config import load

FOLD = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "ss", "é": "e"})
WORD = re.compile(r"\b(?:m|cm|mm|dm)[23]\b|[a-zäöüß]+|\d+(?:[.,]\d+)?", re.I)  # m2/m3 stay one unit token
# specification codes: concrete classes, fire ratings, slip resistance, exposure classes ...
SPEC = re.compile(r"\b(?:C\d{2}/\d{2}|REI\s?\d{2,3}|EI\s?\d{2,3}|F\s?\d{2,3}(?:-A)?|T\d{2}(?:-1)?(?:-RS)?|R\s?\d{1,2}|W\d(?:\.\d)?-[IE]|XC\d|Q\d|B500[AB]?)\b")


DIGRAPH = re.compile(r"(?<=[a-z])(ae|oe|ue)")


def fold(s: str) -> str:
    """Lower case without umlauts; "ae/oe/ue" typed for an umlaut fold the same way."""
    return DIGRAPH.sub(lambda m: m.group(1)[0], s.lower().translate(FOLD))


SUFFIXES = ("ern", "en", "er", "es", "e", "n", "s")


def stem(w: str) -> str:
    """A light German stem for plurals and inflection (Bänder -> band, Fliesen -> flies)."""
    for suf in SUFFIXES:
        if len(w) - len(suf) >= 4 and w.endswith(suf):
            return w[: -len(suf)]
    return w


@cache
def _lex() -> dict[str, object]:
    lx = load("lexicon")
    morph = sorted({fold(m) for m in lx["morphemes"]}, key=len, reverse=True)
    units = {fold(v): k for k, vs in lx["units"].items() for v in vs}
    abbr = {fold(k): fold(v) for k, v in lx["abbreviations"].items()}
    syn = {fold(k): fold(v) for k, v in (lx.get("synonyms") or {}).items()}
    return {
        "morph": morph,
        "morph_set": set(morph),
        "link": [fold(x) for x in lx["linking"]],
        "units": units,
        "abbr": abbr,
        "stop": {fold(s) for s in lx["stopwords"]},
        "syn": syn,
    }


@cache
def split_compound(word: str) -> tuple[str, ...]:
    """Split a folded word into known parts, allowing linking letters between them; () if it does
    not split completely. Prefers the fewest parts."""
    lx = _lex()
    ms: set[str] = lx["morph_set"]  # type: ignore[assignment]
    links: list[str] = lx["link"]  # type: ignore[assignment]
    n = len(word)
    best: list[tuple[int, tuple[str, ...]] | None] = [None] * (n + 1)
    best[0] = (0, ())
    for i in range(n):
        if best[i] is None:
            continue
        cost, parts = best[i]  # type: ignore[misc]
        for j in range(i + 2, n + 1):
            piece = word[i:j]
            if piece in ms:
                for k in [j] + [j + len(lk) for lk in links if word.startswith(lk, j)]:
                    if k <= n and (best[k] is None or best[k][0] > cost + 1):  # type: ignore[index]
                        best[k] = (cost + 1, (*parts, piece))
    return best[n][1] if best[n] and len(best[n][1]) > 1 else ()  # type: ignore[index]


@dataclass
class Tokenizer:
    decompound: bool = True
    expand: bool = True
    keep_numbers: bool = True
    _stats: Counter[str] = field(default_factory=Counter)

    def tokens(self, text: str) -> list[str]:
        lx = _lex()
        t = text.replace("²", "2").replace("³", "3")
        t = re.sub(r"(\w)-(\w)", r"\1 \2", t)  # Brandschutz-Ständerwand -> two words
        t = re.sub(r"([a-zäöüß])([A-ZÄÖÜ])", r"\1 \2", t)  # SockelFl. -> Sockel Fl.
        t = re.sub(r"\.(?=[a-zäöüß])", ". ", t, flags=re.I)  # Stb.wand -> Stb. wand
        out: list[str] = ["s:" + re.sub(r"\s", "", m.group(0)).lower() for m in SPEC.finditer(t)]
        for raw in WORD.findall(t):
            w = fold(raw)
            if w in lx["stop"]:  # type: ignore[operator]
                continue
            if w[0].isdigit():
                if self.keep_numbers:
                    out.append(w.replace(",", "."))
                continue
            if w in lx["units"]:  # type: ignore[operator]
                out.append("u:" + lx["units"][w])  # type: ignore[index]
                continue
            if self.expand and w in lx["abbr"]:  # type: ignore[operator]
                for e in lx["abbr"][w].split():  # type: ignore[index]
                    out += self._word(e)
                continue
            if len(w) < 2:
                continue
            out += self._word(w)
        return out

    def _word(self, w: str) -> list[str]:
        if not self.decompound:
            return [w]
        syn: dict[str, str] = _lex()["syn"]  # type: ignore[assignment]
        parts = split_compound(w) or split_compound(stem(w))
        out = [w, *parts]
        st = stem(w)
        if st != w:
            out.append(st)
        for t in list(out):
            if t in syn:
                out.append(syn[t])
        return out


PLAIN = Tokenizer(decompound=False, expand=False)
CONSTRUCTION = Tokenizer()


class BM25:
    """Okapi BM25 over pre-tokenised documents."""

    def __init__(self, docs: list[list[str]], k1: float = 1.2, b: float = 0.75):
        self.docs = docs
        self.k1, self.b = k1, b
        self.n = len(docs)
        self.avg = sum(len(d) for d in docs) / max(self.n, 1)
        df: Counter[str] = Counter()
        for d in docs:
            df.update(set(d))
        self.idf = {t: math.log(1 + (self.n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.tf = [Counter(d) for d in docs]
        self.len = [len(d) for d in docs]

    def scores(self, q: list[str]) -> list[float]:
        out = []
        for tf, ln in zip(self.tf, self.len, strict=True):
            s = 0.0
            for t in q:
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * ln / self.avg))
            out.append(s)
        return out

    def top(self, q: list[str], k: int = 5) -> list[tuple[int, float]]:
        sc = self.scores(q)
        return sorted(((i, s) for i, s in enumerate(sc) if s > 0), key=lambda x: -x[1])[:k]


def unit(u: str) -> str:
    """Canonical unit for a spelling (m², qm -> m2); unknown spellings pass through."""
    f = fold(u.strip().replace("²", "2").replace("³", "3").rstrip("."))
    units: dict[str, str] = _lex()["units"]  # type: ignore[assignment]
    return units.get(f, u.strip())
