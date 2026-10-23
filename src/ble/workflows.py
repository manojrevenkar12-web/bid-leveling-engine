"""The bid leveling workflow, as harness steps: read the tender, read the bids, resolve positions,
detect deviations, level the bids, build the graph. Each step leaves a decision trace."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ble.config import DATA
from ble.deviate.detect import Finding, detect_bid, detect_tender
from ble.deviate.level import Sheet, level
from ble.graph.build import build
from ble.harness.trace import Decision, Run, code_version, config_version
from ble.ingest.model import BidDoc, TenderDoc
from ble.ingest.readers import read_bid, read_tender_versions
from ble.resolve.match import Matcher, Resolution, resolve


@dataclass
class TenderResult:
    tender_id: str
    versions: list[TenderDoc]
    bids: list[BidDoc]
    resolutions: list[Resolution]
    findings: list[Finding]
    sheet: Sheet
    graph: dict[str, Any]
    run: Run
    timings: dict[str, float] = field(default_factory=dict)


def _ingest_bids(tdir: Path, root: Path) -> tuple[list[BidDoc], list[Decision], float]:
    bids = [read_bid(d, root) for d in sorted((tdir / "bids").iterdir()) if d.is_dir()]
    dec = [Decision(b.bid_id, f"route={b.route}", 1.0 if b.route != "ocr" else 0.85, [{"doc": d} for d in b.doc_ids]) for b in bids]
    return bids, dec, sum(b.cost_eur for b in bids)


def _resolve(bids: list[BidDoc], versions: list[TenderDoc], matcher: Matcher) -> tuple[list[Resolution], list[Decision], float]:
    out, dec = [], []
    for b in bids:
        r = resolve(b, versions, matcher)
        out.append(r)
        dec.append(
            Decision(
                b.bid_id,
                f"priced {r.version}",
                min(1.0, 0.5 + r.version_margin),
                alternatives=[{"version": k, "score": v} for k, v in r.version_scores.items()],
            )
        )
        for m in r.matches:
            ln = b.lines[m.line]
            dec.append(
                Decision(
                    f"{b.bid_id}/line{m.line}",
                    f"prices {m.oz}" if m.oz else "added position",
                    m.p,
                    [ln.evidence.as_dict()],
                    [{"oz": m.runner_up, "p": m.p_runner_up}],
                )
            )
    return out, dec, 0.0


def _detect(bids: list[BidDoc], res: list[Resolution], versions: list[TenderDoc]) -> tuple[list[Finding], list[Decision], float]:
    fs: list[Finding] = []
    for b, r in zip(bids, res, strict=True):
        fs += detect_bid(b, r, versions)
    fs += detect_tender(bids, res, versions)
    dec = [Decision(f"{f.bid_id}/{f.oz or 'bid'}", f.type, f.confidence, f.evidence) for f in fs]
    return fs, dec, 0.0


def level_tender(tender_dir: Path, root: Path = DATA, matcher: Matcher | None = None) -> TenderResult:
    m = matcher or Matcher.load()
    run = Run("bid-leveling")
    versions = run.step(
        "read_tender", read_tender_versions, tender_dir, root, inputs=[str(p.relative_to(root)) for p in sorted((tender_dir / "tender").glob("*.x83"))]
    )
    bids = run.step("read_bids", _ingest_bids, tender_dir, root, inputs=[v.doc_id for v in versions], model="tesseract+pdfplumber")
    res = run.step(
        "resolve_positions", _resolve, bids, versions, m, inputs=[d for b in bids for d in b.doc_ids], model=f"matcher:{m.trained_on.get('source', 'trained')}"
    )
    findings = run.step("detect_deviations", _detect, bids, res, versions, inputs=[t.trace_id for t in run.traces[-1:]])
    sheet = run.step("level_bids", level, versions, bids, res, findings, inputs=[t.trace_id for t in run.traces[-1:]])
    lineage = {"run_id": run.run_id, "code": code_version(), "config": config_version()}
    graph = run.step("build_graph", lambda: build(versions, bids, res, findings, lineage).as_dict(), inputs=[t.trace_id for t in run.traces[-2:]])
    return TenderResult(versions[-1].tender_id, versions, bids, res, findings, sheet, graph, run, {t.step: t.seconds for t in run.traces})
