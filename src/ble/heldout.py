"""Held-out sets: bids written as YAML scripts by someone who has not seen the engine
(heldout/WRITING_BIDS.md), rendered into the documents bidders send, then run once. The first run
is written to reports/heldout/<set>/ and never overwritten; later runs go to latest.json."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from ble.config import DATA, REPORTS, ROOT, TRUTH
from ble.sim import render
from ble.sim.tender import Bid, BidLine, BoQ, Deviation, Position
from ble.text.de import BM25, CONSTRUCTION, PLAIN


def _boq(path: Path, tid: str, version: str) -> BoQ:
    from ble import gaeb

    d = gaeb.read(path.read_bytes())
    pos = [Position(it.oz, it.oz.split(".")[0], "", it.short, it.long, it.unit, it.qty or 0.0) for it in d.items]
    return BoQ(tid, d.project, version, d.categories, pos)


def tenders_from_yaml(base: Path) -> None:
    """A held-out BoQ written as YAML (heldout/WRITING_BIDS.md) becomes the GAEB X83 file the client
    would issue, and a Markdown copy for bid writers."""
    from ble import gaeb

    for f in sorted((base / "tenders").glob("*/LV_*.yaml")):
        t = yaml.safe_load(f.read_text(encoding="utf-8"))
        items = [gaeb.GaebItem(str(p["oz"]), str(p["short"]), str(p.get("long", "")), float(p["qty"]), str(p["unit"])) for p in t["positions"]]
        trades = {str(k).zfill(2): str(v) for k, v in t["trades"].items()}
        f.with_suffix(".x83").write_text(gaeb.write(83, t["project"], t.get("label", f.stem), str(t["date"]), trades, items), encoding="utf-8")


def render_set(version: str) -> list[str]:
    base = ROOT / "heldout" / version
    tenders_from_yaml(base)
    tids = []
    for tdir in sorted((base / "tenders").iterdir()):
        tid = tdir.name
        tids.append(tid)
        out, tr = DATA / "tenders" / tid, TRUTH / "tenders" / tid
        shutil.rmtree(out, ignore_errors=True)
        shutil.rmtree(tr, ignore_errors=True)
        boqs = {}
        for f in sorted(tdir.glob("LV_*.x83")):
            v = f.stem.split("_")[1]
            render.write_bytes(out / "tender" / f.name, f.read_bytes())
            boqs[v] = _boq(f, tid, v)
        rng = np.random.default_rng(int(tid[1:]) + 7)
        for bf in sorted((base / "bids" / tid).glob("*.yaml")):
            s = yaml.safe_load(bf.read_text(encoding="utf-8"))
            bid_id = bf.stem
            v = s.get("priced_version", sorted(boqs)[-1])
            boq = boqs[v]
            fmt = s["format"]
            lines: list[BidLine] = []
            trade = "01"
            for x in s["lines"]:
                oz = x.get("prices_oz")
                trade = str(oz)[:2] if oz else trade  # an added line is printed under the title before it
                lines.append(
                    BidLine(
                        str(x.get("shown_no") or ""),
                        oz,
                        trade,
                        str(x["short"]),
                        x.get("long"),
                        str(x["unit"]),
                        float(x["qty"]),
                        x.get("ep"),
                        x.get("gp"),
                        bool(x.get("included", False)),
                        x.get("product"),
                    )
                )
            for ln in lines:
                if ln.included:
                    ln.ep, ln.gp = 0.0, 0.0
            layout = {"include_long_text": bool(s.get("include_long_text")) or fmt == "gaeb"}
            devs = [Deviation(d["type"], d.get("oz"), str(d.get("detail", ""))) for d in s.get("deviations", [])]
            bid = Bid(
                bid_id,
                tid,
                s["company"],
                "heldout",
                fmt,
                v,
                layout,
                lines,
                [d.__dict__ for d in devs if d.type == "reservation"],
                [str(x) for x in s.get("letter", [])],
                devs,
            )
            d = out / "bids" / bid_id
            date = "2026-09-28"
            if fmt == "gaeb":
                render.write_bytes(d / "angebot.x84", render.bid_gaeb(bid, boq, "2026-09-01" if v == "v1" else "2026-09-15"))
                render.write_bytes(d / "anschreiben.pdf", render.letter_pdf(bid, boq.project, date))
            elif fmt == "pdf":
                render.write_bytes(d / "angebot.pdf", render.bid_pdf(bid, boq, date, with_letter=True))
            elif fmt == "xlsx":
                render.write_bytes(d / "angebot.xlsx", render.bid_xlsx(bid, boq, rng))
                render.write_bytes(d / "anschreiben.pdf", render.letter_pdf(bid, boq.project, date))
            else:
                render.write_bytes(d / "angebot_scan.pdf", render.scan(render.bid_pdf(bid, boq, date, with_letter=True), rng))
            t = bid.truth()
            render.write_bytes(tr / "bids" / f"{bid_id}.json", json.dumps(t, ensure_ascii=False, indent=1))
    return tids


def search_eval(version: str, tids: list[str]) -> dict[str, Any]:
    from ble.ingest.readers import read_tender_versions

    qs = yaml.safe_load((ROOT / "heldout" / version / "search_queries.yaml").read_text(encoding="utf-8"))["queries"]
    latest = {t: read_tender_versions(DATA / "tenders" / t, DATA)[-1] for t in tids}
    out = {}
    for name, tok in (("plain", PLAIN), ("construction", CONSTRUCTION)):
        h1 = h3 = n = 0
        fails = []
        for q in qs:
            t = latest.get(q["tender"])
            if t is None:
                continue
            idx = BM25([tok.tokens(p.short) * 2 + tok.tokens(p.long) for p in t.positions])
            top = [t.positions[i].oz for i, _ in idx.top(tok.tokens(q["q"]), 3)]
            want = set(q["expect"])
            n += 1
            h1 += int(bool(top) and top[0] in want)
            h3 += int(bool(want & set(top)))
            if not want & set(top):
                fails.append(q["q"])
        out[name] = {"queries": n, "hit@1": round(h1 / n, 4) if n else None, "hit@3": round(h3 / n, 4) if n else None, "failures": fails}
    return out


def run_heldout(version: str | None = None) -> dict[str, Any]:
    from ble.evals.score import Score, score_tender
    from ble.runs import export
    from ble.workflows import level_tender

    vs = sorted(p.name for p in (ROOT / "heldout").iterdir() if p.is_dir() and (p / "bids").exists())
    v = version or vs[-1]
    tids = render_set(v)
    s = Score()
    per_tender = {}
    for tid in tids:
        r = level_tender(DATA / "tenders" / tid)
        export(r, REPORTS / "heldout" / v / "runs")
        score_tender(r, s)
        per_tender[tid] = {"bids": len(r.bids), "findings": len(r.findings), "ranking": r.sheet.ranking}
    res: dict[str, Any] = {"set": v, "ran_at": time.strftime("%Y-%m-%d %H:%M:%S"), "score": s.as_dict(), "tenders": per_tender, "search": search_eval(v, tids)}
    target = write_result(REPORTS / "heldout" / v, res)
    print(
        f"[ble] held-out {v}: precision {res['score']['total']['precision']}, recall {res['score']['total']['recall']} -> {target.relative_to(REPORTS.parent)}"
    )
    return res


def write_result(d: Path, res: dict[str, Any]) -> Path:
    """The first run of a set is kept as it was; every later run goes to latest.json."""
    d.mkdir(parents=True, exist_ok=True)
    first = d / "first_run.json"
    target = first if not first.exists() else d / "latest.json"
    target.write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    if target == first:
        (d / "FIRST_RUN.md").write_text(markdown(res), encoding="utf-8")
    return target


def markdown(res: dict[str, Any]) -> str:
    from ble.report import NAMES

    s = res["score"]
    t = s["total"]
    pct = lambda x: "–" if x is None else f"{100 * x:.1f}%"  # noqa: E731
    L = [
        f"# Held-out set {res['set']}: first run",
        "",
        f"Run once on {res['ran_at']}. The bids were written as scripts by an agent that read only `heldout/WRITING_BIDS.md` and the",
        "BoQs, never the engine, and rendered into the documents bidders send. This file is not regenerated; later runs go to",
        "`latest.json`. If the engine is changed after studying these results, this set becomes a regression set and a new one is written.",
        "",
        f"**Findings: precision {pct(t['precision'])}, recall {pct(t['recall'])}** ({t['tp']} found, {t['fp']} false, {t['fn']} missed).",
        "",
        "| Deviation | Found | False | Missed |",
        "|---|---|---|---|",
    ]
    for k, v in s["findings"].items():
        if v["tp"] + v["fp"] + v["fn"]:
            L.append(f"| {NAMES.get(k, k)} | {v['tp']} | {v['fp']} | {v['fn']} |")
    L += ["", "| Route | Lines | Matched correctly | By position number alone |", "|---|---|---|---|"]
    for k, v in s["matching"].items():
        L.append(f"| {k} | {v['lines']} | {pct(v['accuracy'])} | {pct(v['oz_only_accuracy'])} |")
    sv = s["versions"]
    L += ["", f"BoQ version identified: {sv.get('correct', 0)} of {sv.get('correct', 0) + sv.get('wrong', 0)} bids.", ""]
    se = res["search"]
    L += ["| Search | Queries | Hit@1 | Hit@3 |", "|---|---|---|---|"] + [
        f"| {k} | {v['queries']} | {pct(v['hit@1'])} | {pct(v['hit@3'])} |" for k, v in se.items()
    ]
    if s["misses"]:
        L += ["", "## Missed", ""] + [f"- {x['bid']} ({x['route']}): {x['type']} {x['oz'] or ''} – {x['detail']}" for x in s["misses"]]
    if s["false_alarms"]:
        L += ["", "## False findings", ""] + [f"- {x['bid']} ({x['route']}): {x['type']} {x['oz'] or ''} – {x['message']}" for x in s["false_alarms"]]
    if se["construction"]["failures"]:
        L += ["", "## Search queries not answered in the top 3", ""] + [f"- {q}" for q in se["construction"]["failures"]]
    return "\n".join(L) + "\n"
