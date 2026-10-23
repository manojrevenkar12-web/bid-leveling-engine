"""What a tender run exports: the JSON the platform stores (and `ble publish` sends), the project
graph and the decision traces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ble.workflows import TenderResult


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str), encoding="utf-8")


def export(r: TenderResult, out: Path) -> dict[str, Any]:
    """Everything the platform stores for a tender run (also what `ble publish` sends)."""
    d = {
        "tender_id": r.tender_id,
        "project": r.versions[-1].project,
        "run_id": r.run.run_id,
        "versions": [
            {
                "version": v.version,
                "date": v.date,
                "label": v.label,
                "doc_id": v.doc_id,
                "positions": [
                    {"oz": p.oz, "trade": p.trade, "short": p.short, "long": p.long, "qty": p.qty, "unit": p.unit, "evidence": p.evidence.as_dict()}
                    for p in v.positions
                ],
            }
            for v in r.versions
        ],
        "trades": r.versions[-1].trades,
        "bids": [
            {
                "bid_id": b.bid_id,
                "company": b.company,
                "route": b.route,
                "pages": b.pages,
                "cost_eur": b.cost_eur,
                "seconds": b.seconds,
                "stated_total": b.stated_total,
                "priced_version": res.version,
                "version_scores": res.version_scores,
                "doc_ids": b.doc_ids,
                "warnings": b.warnings,
                "lines": [
                    {
                        "idx": ln.idx,
                        "shown_no": ln.shown_no,
                        "short": ln.short,
                        "long": ln.long,
                        "qty": ln.qty,
                        "unit": ln.unit,
                        "ep": ln.ep,
                        "gp": ln.gp,
                        "included": ln.included,
                        "product": ln.product,
                        "confidence": ln.confidence,
                        "evidence": ln.evidence.as_dict(),
                        "oz": m.oz,
                        "match_p": m.p,
                        "runner_up": m.runner_up,
                        "match_needs_review": m.needs_review,
                    }
                    for ln, m in zip(b.lines, res.matches, strict=True)
                ],
                "letter": [{"text": s.text, "evidence": s.evidence.as_dict()} for s in b.letter],
            }
            for b, res in zip(r.bids, r.resolutions, strict=True)
        ],
        "findings": [f.as_dict() for f in r.findings],
        "sheet": r.sheet.as_dict(),
        "traces": [t.as_dict() for t in r.run.traces],
        "graph": {"nodes": len(r.graph["nodes"]), "edges": len(r.graph["edges"])},
    }
    write_json(out / f"{r.tender_id}.json", d)
    write_json(out / f"{r.tender_id}.graph.json", r.graph)
    r.run.write(out / f"{r.tender_id}.traces.jsonl")
    return d
