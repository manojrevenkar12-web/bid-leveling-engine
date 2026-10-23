"""Search over BoQ positions: the construction tokenizer against plain word tokens.

Every tender's positions are an index; each query is asked of every tender that contains an
expected position. Hit@1 and hit@3 count a right position at the top / in the top three."""

from __future__ import annotations

import json
from typing import Any

import yaml

from ble.config import ROOT, TRUTH
from ble.ingest.model import TenderDoc
from ble.text.de import BM25, CONSTRUCTION, PLAIN, Tokenizer


def run(tenders: list[TenderDoc]) -> dict[str, Any]:
    queries = yaml.safe_load((ROOT / "evals" / "search_queries.yaml").read_text(encoding="utf-8"))["queries"]
    out: dict[str, Any] = {}
    for name, tok in (("plain", PLAIN), ("construction", CONSTRUCTION), ("construction_no_split", Tokenizer(decompound=False))):
        h1 = h3 = n = 0
        failures = []
        for t in tenders:
            tpl = (
                {p["oz"]: p["template"] for p in json.loads((TRUTH / "tenders" / t.tender_id / f"boq_{t.version}.json").read_text())["positions"]}
                if (TRUTH / "tenders" / t.tender_id / f"boq_{t.version}.json").exists()
                else {}
            )
            docs = [tok.tokens(p.short) * 2 + tok.tokens(p.long) for p in t.positions]
            idx = BM25(docs)
            for q in queries:
                want = {p.oz for p in t.positions if tpl.get(p.oz) in q["expect"]}
                if not want:
                    continue
                n += 1
                top = [t.positions[i].oz for i, _ in idx.top(tok.tokens(q["q"]), 3)]
                h1 += int(bool(top) and top[0] in want)
                h3 += int(bool(want & set(top)))
                if not (want & set(top)):
                    failures.append({"tender": t.tender_id, "query": q["q"]})
        out[name] = {"queries": n, "hit@1": round(h1 / n, 4) if n else None, "hit@3": round(h3 / n, 4) if n else None, "failures": failures[:15]}
    return out
