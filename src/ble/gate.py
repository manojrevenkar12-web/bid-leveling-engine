"""The release gate (config/release.yaml) over the reports `ble run` wrote."""

from __future__ import annotations

import json
from typing import Any

from ble.config import REPORTS, load


def _read(name: str) -> Any:
    p = REPORTS / name
    return json.loads(p.read_text()) if p.exists() else None


def gate() -> dict[str, Any]:
    c = load("release")
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "passed": bool(ok), "detail": detail})

    ev = _read("eval_test.json")
    if ev is None:
        add("test evaluation", False, "missing")
    else:
        t = ev["total"]
        add("findings precision", (t["precision"] or 0) >= c["findings"]["min_precision"], f"{t['precision']} (needs {c['findings']['min_precision']})")
        add("findings recall", (t["recall"] or 0) >= c["findings"]["min_recall"], f"{t['recall']} (needs {c['findings']['min_recall']})")
        for typ in c["findings"]["must_find"]:
            f = ev["findings"].get(typ)
            if not f or f["tp"] + f["fn"] < 3:
                continue
            add(f"recall: {typ}", f["recall"] >= c["findings"]["min_type_recall"], f"{f['tp']} of {f['tp'] + f['fn']} found")
        rv = ev["review"]
        auto = rv.get("true_auto", 0) + rv.get("false_auto", 0)
        share = rv.get("false_auto", 0) / auto if auto else 0.0
        add("wrong findings auto-confirmed", share <= c["findings"]["max_false_auto_confirmed_share"], f"{rv.get('false_auto', 0)} of {auto} auto-confirmed findings ({share:.1%})")
        for route, m in ev["matching"].items():
            add(f"matching accuracy: {route}", (m["accuracy"] or 0) >= c["matching"]["min_accuracy_per_route"], f"{m['accuracy']} on {m['lines']} lines (position number alone: {m['oz_only_accuracy']})")
            share = m.get("wrong_not_flagged", 0) / m["lines"] if m["lines"] else 0
            add(f"wrong matches sent to review: {route}", share <= c["matching"]["max_wrong_unflagged_share"], f"{m.get('wrong_not_flagged', 0)} wrong and unflagged")
        v = ev["versions"]
        acc = v.get("correct", 0) / max(1, v.get("correct", 0) + v.get("wrong", 0))
        add("BoQ version priced", acc >= c["versions"]["min_accuracy"], f"{v.get('correct', 0)} of {v.get('correct', 0) + v.get('wrong', 0)} bids")
    s = _read("search.json")
    if s:
        con, pl = s["test"]["construction"], s["test"]["plain"]
        add("search hit@3", (con["hit@3"] or 0) >= c["search"]["min_hit_at_3"], f"{con['hit@3']} vs plain tokens {pl['hit@3']}")
        if c["search"]["must_beat_plain"]:
            add("search beats plain tokens", (con["hit@3"] or 0) > (pl["hit@3"] or 0), f"{con['hit@3']} > {pl['hit@3']}")
    res = {"passed": all(x["passed"] for x in checks) and bool(checks), "checks": checks}
    (REPORTS / "gate.json").write_text(json.dumps(res, indent=1))
    return res
