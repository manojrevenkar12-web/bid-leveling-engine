import json

import pytest
from helpers import small_result

from ble.harness.trace import SCHEMA_VERSION, Decision, Run


def test_step_records_trace_with_decisions_and_cost(tmp_path):
    run = Run("wf")
    out = run.step("s1", lambda x: (x * 2, [Decision("a", "yes", 0.9)], 0.25), 21, inputs=["doc@abc"], model="m1")
    assert out == 42
    t = run.traces[0]
    assert (t.schema, t.step, t.inputs, t.model, t.cost_eur, t.status) == (SCHEMA_VERSION, "s1", ["doc@abc"], "m1", 0.25, "ok")
    assert t.decisions[0].decision == "yes" and t.code_version and len(t.config_version) == 12
    run.write(tmp_path / "t.jsonl")
    rows = [json.loads(x) for x in (tmp_path / "t.jsonl").read_text().splitlines()]
    assert rows[0]["run_id"] == run.run_id and rows[0]["decisions"][0]["subject"] == "a"


def test_retries_then_error_trace():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("transient")
        return [1, 2, 3]

    run = Run("wf")
    assert run.step("flaky", flaky, retries=1) == [1, 2, 3]
    assert run.traces[-1].status == "ok after 1 retries" and run.traces[-1].outputs == {"items": 3}
    with pytest.raises(ValueError):
        run.step("broken", lambda: (_ for _ in ()).throw(ValueError("bad")))
    assert run.traces[-1].status == "error" and "bad" in run.traces[-1].error


def test_langfuse_batch_shape():
    run = Run("wf")
    run.step("a", lambda: 1)
    ev = run.langfuse_batch()
    assert ev[0]["type"] == "trace-create" and ev[1]["type"] == "span-create" and ev[1]["body"]["traceId"] == run.run_id


def test_graph_has_lineage_and_ontology_types():
    r = small_result()
    g = r.graph
    types = {n["type"] for n in g["nodes"]}
    assert {"Tender", "Bid", "Position"} <= types
    assert all("lineage" in n for n in g["nodes"]) and all("lineage" in e for e in g["edges"])
    ids = {n["id"] for n in g["nodes"]}
    assert all(e["src"] in ids and e["dst"] in ids for e in g["edges"])


def test_export_shape(tmp_path):
    from ble.runs import export

    d = export(small_result(), tmp_path)
    assert (tmp_path / "X01.json").exists() and (tmp_path / "X01.graph.json").exists() and (tmp_path / "X01.traces.jsonl").exists()
    assert {"tender_id", "run_id", "versions", "bids", "findings", "sheet", "traces", "trades"} <= set(d)
    assert all(ln["oz"] for b in d["bids"] for ln in b["lines"])
