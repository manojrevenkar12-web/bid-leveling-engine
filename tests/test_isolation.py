"""The engine decides from the documents only. Nothing that reads, matches, detects, levels or
answers may import the simulator, the answer key or the evaluation code, or touch the truth path."""

import ast
import json
from pathlib import Path

from ble.heldout import write_result

SRC = Path(__file__).resolve().parents[1] / "src" / "ble"
ENGINE = ["gaeb.py", "chat.py", "workflows.py", "runs.py", "ingest", "text", "resolve/match.py", "deviate", "graph", "harness", "service"]
BANNED_MODULES = ("ble.sim", "ble.evals", "ble.heldout", "ble.pipeline", "ble.gate", "ble.report")
BANNED_NAMES = {"TRUTH", "WORLD", "world"}


def _files():
    for e in ENGINE:
        p = SRC / e
        yield from ([p] if p.suffix == ".py" else sorted(p.rglob("*.py")))


def test_engine_never_imports_the_answer_key():
    bad = []
    for f in _files():
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module
                if mod.startswith(BANNED_MODULES) or (mod == "ble.config" and {a.name for a in node.names} & BANNED_NAMES):
                    bad.append(f"{f.relative_to(SRC)}: from {mod} import {[a.name for a in node.names]}")
                if mod == "ble" and {a.name for a in node.names} & {"sim", "evals", "heldout", "pipeline"}:
                    bad.append(f"{f.relative_to(SRC)}: from ble import ...")
            elif isinstance(node, ast.Import):
                bad += [f"{f.relative_to(SRC)}: import {a.name}" for a in node.names if a.name.startswith(BANNED_MODULES)]
    assert bad == []


def test_engine_files_exist():
    assert len(list(_files())) >= 20


def test_heldout_first_run_is_never_overwritten(tmp_path):
    first = {"set": "v1", "ran_at": "t0", "score": {"total": {"precision": 0.9, "recall": 0.8, "tp": 9, "fp": 1, "fn": 2}, "findings": {}, "matching": {}, "versions": {}, "misses": [], "false_alarms": []}, "search": {"construction": {"queries": 0, "hit@1": None, "hit@3": None, "failures": []}}}
    assert write_result(tmp_path, first).name == "first_run.json"
    md = (tmp_path / "FIRST_RUN.md").read_text()
    later = json.loads(json.dumps(first))
    later["score"]["total"]["precision"] = 1.0
    assert write_result(tmp_path, later).name == "latest.json"
    assert json.loads((tmp_path / "first_run.json").read_text())["score"]["total"]["precision"] == 0.9
    assert (tmp_path / "FIRST_RUN.md").read_text() == md
