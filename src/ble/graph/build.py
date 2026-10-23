"""The project graph: canonical entities of a tender from the ontology (config/ontology.yaml),
with lineage on every node and edge, and per-customer extension attributes."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from ble.config import load
from ble.ingest.model import BidDoc, TenderDoc
from ble.resolve.match import Resolution
from ble.text.de import fold


@dataclass
class Graph:
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: list[dict[str, Any]] = field(default_factory=list)

    def node(self, typ: str, key: str, lineage: dict[str, Any], **props: Any) -> str:
        nid = f"{typ}:{key}"
        n = self.nodes.setdefault(nid, {"id": nid, "type": typ, "props": {}, "lineage": lineage})
        n["props"].update({k: v for k, v in props.items() if v is not None})
        return nid

    def edge(self, typ: str, src: str, dst: str, lineage: dict[str, Any], **props: Any) -> None:
        self.edges.append({"type": typ, "src": src, "dst": dst, "props": props, "lineage": lineage})

    def as_dict(self) -> dict[str, Any]:
        return {"ontology_version": load("ontology")["version"], "nodes": list(self.nodes.values()), "edges": self.edges}


def _ext(text: str) -> dict[str, str]:
    out = {}
    for name, spec in load("ontology")["extensions"].items():
        t = fold(text)
        for r in spec["rules"]:
            if re.search(r["match"], t):
                out[name] = r["value"]
                break
    return out


def build(versions: list[TenderDoc], bids: list[BidDoc], resolutions: list[Resolution], findings: list[Any], run: dict[str, str]) -> Graph:
    g = Graph()
    cur = versions[-1]
    tid = cur.tender_id
    lin = lambda *docs: {**run, "sources": [d for d in docs if d]}  # noqa: E731
    proj = g.node("Project", fold(cur.project), lin(cur.doc_id), name=cur.project)
    ten = g.node("Tender", tid, lin(cur.doc_id), tender_id=tid)
    g.edge("FOR_PROJECT", ten, proj, lin(cur.doc_id))
    prev = None
    for v in versions:
        doc = g.node("Document", v.doc_id, lin(v.doc_id), path=v.doc_id.split("@")[0], sha256=v.doc_id.split("@")[1])
        bv = g.node("BoQVersion", f"{tid}/{v.version}", lin(v.doc_id), version=v.version, date=v.date, label=v.label)
        g.edge("HAS_VERSION", ten, bv, lin(v.doc_id))
        g.edge("READ_FROM", bv, doc, lin(v.doc_id))
        if prev:
            g.edge("SUPERSEDES", bv, prev, lin(v.doc_id))
        prev = bv
        for code, name in v.trades.items():
            g.node("Trade", f"{tid}/{code}", lin(v.doc_id), code=code, name=name)
        for p in v.positions:
            pid = g.node("Position", f"{tid}/{p.oz}", lin(v.doc_id), oz=p.oz, short=p.short, long=p.long, unit=p.unit, **_ext(p.short + " " + p.long))
            th = hashlib.sha1(p.long.encode()).hexdigest()[:10]
            g.edge("IN_VERSION", pid, bv, lin(v.doc_id), qty=p.qty, unit=p.unit, text_hash=th, xml_line=p.evidence.xml_line)
            g.edge("IN_TRADE", pid, f"Trade:{tid}/{p.trade}", lin(v.doc_id))
    for b, r in zip(bids, resolutions, strict=True):
        bidder = g.node("Bidder", fold(b.company) or b.bid_id, lin(*b.doc_ids), company=b.company)
        bid = g.node("Bid", b.bid_id, lin(*b.doc_ids), bid_id=b.bid_id, route=b.route, stated_total=b.stated_total, pages=b.pages, cost_eur=b.cost_eur)
        g.edge("SUBMITTED", bidder, bid, lin(*b.doc_ids))
        g.edge("FOR_TENDER", bid, ten, lin(*b.doc_ids))
        g.edge("PRICED_VERSION", bid, f"BoQVersion:{tid}/{r.version}", lin(*b.doc_ids), version_scores=r.version_scores)
        for d in b.doc_ids:
            g.node("Document", d, lin(d), path=d.split("@")[0], sha256=d.split("@")[1])
        for m in r.matches:
            ln = b.lines[m.line]
            lid = g.node(
                "BidLine", f"{b.bid_id}/{ln.idx}", lin(ln.evidence.doc), shown_no=ln.shown_no, short=ln.short, qty=ln.qty, unit=ln.unit, ep=ln.ep, gp=ln.gp
            )
            g.edge("IN_BID", lid, bid, lin(ln.evidence.doc))
            if m.oz:
                g.edge("PRICES", lid, f"Position:{tid}/{m.oz}", lin(ln.evidence.doc), p=m.p, needs_review=m.needs_review, runner_up=m.runner_up)
    for f in findings:
        fid = g.node(
            "Finding",
            f.id,
            lin(*[e["doc"] for e in f.evidence]),
            type=f.type,
            severity=f.severity,
            message=f.message,
            confidence=f.confidence,
            needs_review=f.needs_review,
        )
        g.edge("ABOUT", fid, f"Bid:{f.bid_id}", lin())
        if f.oz:
            g.edge("CONCERNS", fid, f"Position:{tid}/{f.oz}", lin())
        for e in f.evidence:
            doc, _, sha = e["doc"].partition("@")
            g.node("Document", e["doc"], lin(e["doc"]), path=doc, sha256=sha or None)  # every edge ends at a node
            g.edge("EVIDENCED_BY", fid, f"Document:{e['doc']}", lin(e["doc"]), **{k: v for k, v in e.items() if k != "doc"})
    return g
