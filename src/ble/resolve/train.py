"""Fit the position matcher on development tenders (pairs of bid line and BoQ position labelled by
the answer key), and compare it with the hand-set weights."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression

from ble.config import DATA
from ble.evals import truth
from ble.ingest.model import BidDoc, TenderDoc
from ble.ingest.readers import read_bid, read_tender_versions
from ble.resolve.match import FEATURES, Matcher, features


def pairs(tids: list[str]) -> tuple[np.ndarray, np.ndarray]:
    X, y = [], []
    for tid in tids:
        tdir = DATA / "tenders" / tid
        versions = read_tender_versions(tdir, DATA)
        for bdir in sorted((tdir / "bids").iterdir()):
            bid: BidDoc = read_bid(bdir, DATA)
            tb = truth.bid(tid, bid.bid_id)
            boq: TenderDoc = next(v for v in versions if v.version == tb["priced_version"])
            F = features(bid, boq)
            lt = truth.line_truth(bid)
            for i, t in enumerate(lt):
                if t is False:
                    continue
                for j, p in enumerate(boq.positions):
                    X.append(F[i, j])
                    y.append(int(p.oz == t))
    return np.asarray(X), np.asarray(y)


def train(tids: list[str]) -> tuple[Matcher, dict[str, Any]]:
    X, y = pairs(tids)
    lr = LogisticRegression(C=1.0, max_iter=2000, class_weight={0: 1.0, 1: 3.0}).fit(X, y)
    m = Matcher([round(float(c), 4) for c in lr.coef_[0]], round(float(lr.intercept_[0]), 4), {"source": "trained", "tenders": tids, "pairs": len(y), "positives": int(y.sum())})
    return m, {"features": dict(zip(FEATURES, m.coef, strict=True)), "pairs": len(y), "positives": int(y.sum())}
