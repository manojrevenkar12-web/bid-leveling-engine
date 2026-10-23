"""`ble run`: build the world, fit the matcher on dev tenders, level every tender, score dev and
test against the answer key, evaluate search, measure ingestion, then write the report and check
the gate."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ble.config import DATA, MODELS, REPORTS
from ble.evals import search
from ble.evals.score import Score, score_tender
from ble.resolve.match import Matcher
from ble.sim.build import SPLITS, build
from ble.workflows import TenderResult, level_tender


def _w(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str), encoding="utf-8")


def _log(msg: str) -> None:
    print(f"[ble] {msg}", flush=True)


def export(r: TenderResult, out: Path) -> dict[str, Any]:
    """Everything the platform stores for a tender run (also what `ble publish` sends)."""
    d = {
        "tender_id": r.tender_id,
        "project": r.versions[-1].project,
        "run_id": r.run.run_id,
        "versions": [{"version": v.version, "date": v.date, "label": v.label, "doc_id": v.doc_id, "positions": [{"oz": p.oz, "trade": p.trade, "short": p.short, "long": p.long, "qty": p.qty, "unit": p.unit, "evidence": p.evidence.as_dict()} for p in v.positions]} for v in r.versions],
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
                    {"idx": ln.idx, "shown_no": ln.shown_no, "short": ln.short, "long": ln.long, "qty": ln.qty, "unit": ln.unit, "ep": ln.ep, "gp": ln.gp, "included": ln.included, "product": ln.product, "confidence": ln.confidence, "evidence": ln.evidence.as_dict(), "oz": m.oz, "match_p": m.p, "runner_up": m.runner_up, "match_needs_review": m.needs_review}
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
    _w(out / f"{r.tender_id}.json", d)
    _w(out / f"{r.tender_id}.graph.json", r.graph)
    r.run.write(out / f"{r.tender_id}.traces.jsonl")
    return d


def level_split(split: str, matcher: Matcher, out: Path) -> tuple[list[TenderResult], Score]:
    s = Score()
    results = []
    for tid in SPLITS[split]:
        t0 = time.perf_counter()
        r = level_tender(DATA / "tenders" / tid, matcher=matcher)
        export(r, out)
        score_tender(r, s)
        results.append(r)
        _log(f"{tid}: {len(r.bids)} bids, {len(r.findings)} findings, {time.perf_counter() - t0:.1f}s")
    return results, s


def ingest_stats(results: list[TenderResult]) -> dict[str, Any]:
    by: dict[str, dict[str, float]] = {}
    for r in results:
        for b in r.bids:
            d = by.setdefault(b.route, {"bids": 0, "pages": 0, "seconds": 0.0, "cost_eur": 0.0})
            d["bids"] += 1
            d["pages"] += b.pages
            d["seconds"] += b.seconds
            d["cost_eur"] += b.cost_eur
    for d in by.values():
        d["pages_per_minute"] = round(60 * d["pages"] / d["seconds"], 1) if d["seconds"] else None
        d["eur_per_page"] = round(d["cost_eur"] / d["pages"], 5) if d["pages"] else None
        d["seconds"] = round(d["seconds"], 2)
        d["cost_eur"] = round(d["cost_eur"], 4)
    return by


def run(quick: bool = False, skip_world: bool = False) -> dict[str, Any]:
    from ble.gate import gate
    from ble.report import write_report
    from ble.resolve.train import train

    t0 = time.perf_counter()
    if not skip_world:
        _log("building the tender world")
        build("all")
    _log("fitting the position matcher on dev tenders")
    m, info = train(SPLITS["dev"])
    m.save(MODELS / "matcher.json")
    _w(REPORTS / "matcher.json", info)
    out = REPORTS / "runs"
    dev, s_dev = level_split("dev", m, out)
    test, s_test = level_split("test", m, out)
    _w(REPORTS / "eval_dev.json", s_dev.as_dict())
    _w(REPORTS / "eval_test.json", s_test.as_dict())
    # the hand-set weights on the same test tenders, to show what fitting bought
    if not quick:
        _, s_def = level_split("test", Matcher.default(), REPORTS / "runs_default_matcher")
        _w(REPORTS / "eval_test_default_matcher.json", {"matching": s_def.as_dict()["matching"], "total": s_def.as_dict()["total"]})
    _w(REPORTS / "search.json", {"dev": search.run([r.versions[-1] for r in dev]), "test": search.run([r.versions[-1] for r in test])})
    _w(REPORTS / "ingest.json", ingest_stats(dev + test))
    res = gate()
    write_report()
    _log(f"done in {time.perf_counter() - t0:.0f}s; gate {'passed' if res['passed'] else 'FAILED'}")
    return res
