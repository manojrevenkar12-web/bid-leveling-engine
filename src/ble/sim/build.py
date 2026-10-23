"""`ble world`: write tenders and bids to data/ and what is really in them to truth/.

data/tenders/<T>/tender/LV_v1.x83 (and LV_v2.x83 for an addendum)
data/tenders/<T>/bids/<bid>/angebot.{x84,pdf,xlsx} + anschreiben.pdf, or angebot_scan.pdf
truth/tenders/<T>/boq_v1.json, bids/<bid>.json
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from ble.config import DATA, TRUTH
from ble.sim import render
from ble.sim.tender import make_bids, make_boq

SPLITS = {"dev": [f"T{i:02d}" for i in range(1, 13)], "test": [f"T{i:02d}" for i in range(51, 59)]}
DATES = {"v1": "2026-09-01", "v2": "2026-09-15"}


def build_tender(tid: str, data: Path = DATA, truth: Path = TRUTH) -> dict[str, Any]:
    seed = int(tid[1:]) * 7919 + 13
    rng = np.random.default_rng(seed)
    boqs = make_boq(tid, rng)
    tdir, ttruth = data / "tenders" / tid, truth / "tenders" / tid
    for b in boqs:
        render.write_bytes(tdir / "tender" / f"LV_{b.version}.x83", render.boq_gaeb(b, DATES[b.version]))
        render.write_bytes(ttruth / f"boq_{b.version}.json", json.dumps({"tender_id": tid, "project": b.project, "version": b.version, "positions": [asdict(p) for p in b.positions]}, ensure_ascii=False, indent=1))
    bids = make_bids(boqs, rng)
    by_v = {b.version: b for b in boqs}
    for bid in bids:
        boq = by_v[bid.priced_version]
        d = tdir / "bids" / bid.bid_id
        date = "2026-09-28"
        if bid.format == "gaeb":
            render.write_bytes(d / "angebot.x84", render.bid_gaeb(bid, boq, DATES[boq.version]))
            render.write_bytes(d / "anschreiben.pdf", render.letter_pdf(bid, boq.project, date))
        elif bid.format == "pdf":
            render.write_bytes(d / "angebot.pdf", render.bid_pdf(bid, boq, date, with_letter=True, qty_decimals=int(rng.choice([2, 3]))))
        elif bid.format == "xlsx":
            render.write_bytes(d / "angebot.xlsx", render.bid_xlsx(bid, boq, rng))
            render.write_bytes(d / "anschreiben.pdf", render.letter_pdf(bid, boq.project, date))
        else:
            pdf = render.bid_pdf(bid, boq, date, with_letter=True, qty_decimals=3)
            render.write_bytes(d / "angebot_scan.pdf", render.scan(pdf, rng))
        render.write_bytes(ttruth / "bids" / f"{bid.bid_id}.json", json.dumps(bid.truth(), ensure_ascii=False, indent=1))
    return {"tender": tid, "versions": [b.version for b in boqs], "positions": len(boqs[-1].positions), "bids": [(b.bid_id, b.persona, b.format) for b in bids]}


def build(split: str = "all", clean: bool = True) -> list[dict[str, Any]]:
    tids = SPLITS["dev"] + SPLITS["test"] if split == "all" else SPLITS[split]
    if clean:
        for tid in tids:
            shutil.rmtree(DATA / "tenders" / tid, ignore_errors=True)
            shutil.rmtree(TRUTH / "tenders" / tid, ignore_errors=True)
    return [build_tender(t) for t in tids]
