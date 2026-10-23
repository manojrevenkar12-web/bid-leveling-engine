"""ble: the command line.

  ble world [--split dev|test|all]   generate tenders and bids (and the answer key in truth/)
  ble level <tender-dir> [--out DIR]  run the bid leveling workflow on one tender folder
  ble train                           fit the position matcher on the dev tenders
  ble eval [--split test]             score a split against the answer key
  ble heldout [--version v1]          first run of a blind held-out set (kept as written)
  ble run [--quick] [--skip-world]    everything, then the report and the gate
  ble report | ble gate
  ble publish <run.json> --api URL    send a tender run to the platform API
  ble serve [--port 8001]             the AI service (search, chat, workflow runs)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ble", description="Bid leveling engine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("world")
    w.add_argument("--split", default="all")
    lv = sub.add_parser("level")
    lv.add_argument("tender")
    lv.add_argument("--out", default=None)
    sub.add_parser("train")
    e = sub.add_parser("eval")
    e.add_argument("--split", default="test")
    h = sub.add_parser("heldout")
    h.add_argument("--version", default=None)
    r = sub.add_parser("run")
    r.add_argument("--quick", action="store_true")
    r.add_argument("--skip-world", action="store_true")
    sub.add_parser("report")
    sub.add_parser("gate")
    pb = sub.add_parser("publish")
    pb.add_argument("run_json")
    pb.add_argument("--api", default="http://127.0.0.1:3000")
    pb.add_argument("--key", default=None)
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8001)
    a = ap.parse_args(argv)

    if a.cmd == "world":
        from ble.sim.build import build

        for t in build(a.split):
            print(t["tender"], t["versions"], t["positions"], "positions,", len(t["bids"]), "bids")
    elif a.cmd == "level":
        from ble.config import DATA, REPORTS
        from ble.pipeline import export
        from ble.workflows import level_tender

        tdir = Path(a.tender) if Path(a.tender).is_dir() else DATA / "tenders" / a.tender
        res = level_tender(tdir)
        d = export(res, Path(a.out) if a.out else REPORTS / "runs")
        for b in d["sheet"]["ranking"]:
            print(f"{b['rank']}. {b['company']:<40} {b['comparable_total']:>14,.2f} € (stated rank {b['stated_rank']})")
        print(f"{len(d['findings'])} findings, {sum(f['needs_review'] for f in d['findings'])} for review")
    elif a.cmd == "train":
        from ble.config import MODELS
        from ble.resolve.train import train
        from ble.sim.build import SPLITS

        m, info = train(SPLITS["dev"])
        m.save(MODELS / "matcher.json")
        print(json.dumps(info, indent=1))
    elif a.cmd == "eval":
        from ble.config import DATA
        from ble.evals.score import Score, score_tender
        from ble.sim.build import SPLITS
        from ble.workflows import level_tender

        s = Score()
        for tid in SPLITS[a.split]:
            score_tender(level_tender(DATA / "tenders" / tid), s)
        d = s.as_dict()
        print(json.dumps({k: d[k] for k in ("total", "findings", "matching", "versions")}, indent=1))
    elif a.cmd == "heldout":
        from ble.heldout import run_heldout

        run_heldout(a.version)
    elif a.cmd == "run":
        from ble.pipeline import run

        res = run(a.quick, a.skip_world)
        _gate(res)
        return 0 if res["passed"] else 1
    elif a.cmd == "report":
        from ble.report import write_report

        write_report()
    elif a.cmd == "gate":
        from ble.gate import gate

        res = gate()
        _gate(res)
        return 0 if res["passed"] else 1
    elif a.cmd == "publish":
        from ble.service.client import publish

        print(json.dumps(publish(Path(a.run_json), a.api, a.key), indent=1))
    elif a.cmd == "serve":
        import uvicorn

        uvicorn.run("ble.service.app:app", host=a.host, port=a.port)
    return 0


def _gate(res: dict) -> None:
    for c in res["checks"]:
        print(f"{'PASS' if c['passed'] else 'FAIL'}  {c['check']}: {c['detail']}")
    print("gate:", "passed" if res["passed"] else "FAILED")


if __name__ == "__main__":
    sys.exit(main())
