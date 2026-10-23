"""Slow: build simulated tenders, run the workflow on them and score it against the answer key."""

import hashlib
import json
import os
import subprocess
import sys

import pytest

from ble.config import DATA
from ble.resolve.match import Matcher

pytestmark = pytest.mark.slow


def _digest(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


def test_world_is_deterministic(tmp_path):
    from ble.sim.build import build_tender

    build_tender("T07", data=tmp_path / "a", truth=tmp_path / "at")
    build_tender("T07", data=tmp_path / "b", truth=tmp_path / "bt")
    assert _digest(tmp_path / "a") == _digest(tmp_path / "b")
    assert _digest(tmp_path / "at") == _digest(tmp_path / "bt")


@pytest.fixture(scope="module")
def t53():
    from ble.sim.build import build_tender

    if not (DATA / "tenders" / "T53" / "bids").exists():
        build_tender("T53")
    return DATA / "tenders" / "T53"


def test_workflow_finds_what_was_put_in(t53):
    from ble.evals.score import Score, score_tender
    from ble.workflows import level_tender

    r = level_tender(t53, matcher=Matcher.default())
    s = Score()
    score_tender(r, s)
    d = s.as_dict()
    assert d["total"]["precision"] >= 0.8 and d["total"]["recall"] >= 0.8, d["total"]
    for route, m in d["matching"].items():
        assert m["accuracy"] >= 0.95, (route, m)
    assert [t.step for t in r.run.traces] == ["read_tender", "read_bids", "resolve_positions", "detect_deviations", "level_bids", "build_graph"]
    assert all(f.evidence for f in r.findings)


def test_workflow_runs_without_the_answer_key(t53, tmp_path):
    """The same findings come out when the truth directory does not exist."""
    code = (
        "import json,sys; from pathlib import Path; from ble.workflows import level_tender; from ble.resolve.match import Matcher; "
        "r = level_tender(Path(sys.argv[1]), matcher=Matcher.default()); print(json.dumps(sorted(f.id for f in r.findings)))"
    )
    env = {**os.environ, "BLE_TRUTH": str(tmp_path / "no-truth-here")}
    blind = subprocess.run([sys.executable, "-c", code, str(t53)], env=env, capture_output=True, text=True, check=True)
    normal = subprocess.run([sys.executable, "-c", code, str(t53)], capture_output=True, text=True, check=True)
    assert json.loads(blind.stdout) == json.loads(normal.stdout) != []
