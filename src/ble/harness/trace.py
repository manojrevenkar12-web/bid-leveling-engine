"""The workflow harness and its decision-trace standard.

A workflow is a list of steps. Each step reads typed inputs and returns outputs, and the harness
records one trace per step: what it read (document ids with content hashes), which code, config and
model versions decided, what it decided (with confidence and evidence), how long it took and what it
cost. A new use case is a new list of steps; tracing, retries, caching and Prefect orchestration
come with the harness.

Traces export as JSON lines and, when LANGFUSE_* is configured, in Langfuse's ingestion shape.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import subprocess
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ble.config import CONFIG, ROOT

SCHEMA_VERSION = "decision-trace/1"


@functools.cache
def code_version() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip() or "dev"
    except Exception:
        return os.environ.get("BLE_CODE_VERSION", "dev")


@functools.cache
def config_version() -> str:
    h = hashlib.sha256()
    for p in sorted(CONFIG.glob("*.yaml")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


@dataclass
class Decision:
    subject: str  # what was decided about: a bid line, a position, a bid
    decision: str
    confidence: float
    evidence: list[dict[str, Any]] = field(default_factory=list)
    alternatives: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class StepTrace:
    schema: str
    run_id: str
    trace_id: str
    workflow: str
    step: str
    inputs: list[str]  # document ids or upstream trace ids
    outputs: dict[str, Any]
    decisions: list[Decision]
    code_version: str
    config_version: str
    model: str
    started_at: float
    seconds: float
    cost_eur: float
    status: str = "ok"
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Run:
    workflow: str
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    traces: list[StepTrace] = field(default_factory=list)

    def step(self, name: str, fn: Callable[..., Any], *args: Any, inputs: list[str] | None = None, model: str = "rules", retries: int = 0, **kw: Any) -> Any:
        """Run one step and record its trace. The step may return (result, decisions, cost_eur)."""
        t0, started = time.perf_counter(), time.time()
        attempt, err = 0, None
        while True:
            try:
                out = fn(*args, **kw)
                break
            except Exception as e:  # recorded, then re-raised once retries are spent
                err = e
                attempt += 1
                if attempt > retries:
                    self.traces.append(
                        StepTrace(
                            SCHEMA_VERSION,
                            self.run_id,
                            uuid.uuid4().hex[:16],
                            self.workflow,
                            name,
                            inputs or [],
                            {},
                            [],
                            code_version(),
                            config_version(),
                            model,
                            started,
                            round(time.perf_counter() - t0, 4),
                            0.0,
                            "error",
                            repr(e),
                        )
                    )
                    raise
        decisions: list[Decision] = []
        cost = 0.0
        result = out
        if isinstance(out, tuple) and len(out) == 3 and isinstance(out[1], list):
            result, decisions, cost = out
        summary = _summary(result)
        self.traces.append(
            StepTrace(
                SCHEMA_VERSION,
                self.run_id,
                uuid.uuid4().hex[:16],
                self.workflow,
                name,
                inputs or [],
                summary,
                decisions,
                code_version(),
                config_version(),
                model,
                started,
                round(time.perf_counter() - t0, 4),
                round(float(cost), 6),
                "ok" if err is None else f"ok after {attempt} retries",
            )
        )
        return result

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for t in self.traces:
                f.write(json.dumps(t.as_dict(), ensure_ascii=False, default=str) + "\n")

    def langfuse_batch(self) -> list[dict[str, Any]]:
        """The run as Langfuse ingestion events: one trace, one span per step."""
        ev = [{"id": self.run_id, "type": "trace-create", "body": {"id": self.run_id, "name": self.workflow, "metadata": {"schema": SCHEMA_VERSION}}}]
        for t in self.traces:
            ev.append(
                {
                    "id": t.trace_id,
                    "type": "span-create",
                    "body": {
                        "id": t.trace_id,
                        "traceId": self.run_id,
                        "name": t.step,
                        "startTime": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t.started_at)) + "Z",
                        "metadata": {
                            "code": t.code_version,
                            "config": t.config_version,
                            "model": t.model,
                            "cost_eur": t.cost_eur,
                            "decisions": len(t.decisions),
                        },
                        "input": t.inputs,
                        "output": t.outputs,
                        "level": "ERROR" if t.status == "error" else "DEFAULT",
                    },
                }
            )
        return ev


def _summary(x: Any) -> dict[str, Any]:
    if isinstance(x, list):
        return {"items": len(x)}
    if isinstance(x, dict):
        return {k: (len(v) if isinstance(v, list | dict) else v) for k, v in list(x.items())[:20] if isinstance(v, int | float | str | list | dict)}
    if hasattr(x, "__dataclass_fields__"):
        d = {}
        for k in list(x.__dataclass_fields__)[:12]:
            v = getattr(x, k)
            d[k] = len(v) if isinstance(v, list | dict) else (v if isinstance(v, int | float | str) or v is None else str(v)[:60])
        return d
    return {"value": str(x)[:120]}
