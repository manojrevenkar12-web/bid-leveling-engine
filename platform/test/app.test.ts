// API tests against a real Postgres (TEST_DATABASE_URL, default the local ble_test database).
import { readFileSync } from "node:fs";
import { afterAll, beforeEach, describe, expect, it } from "vitest";
import pg from "pg";
import { buildApp, storeRun, type RunExport } from "../src/app.js";
import { migrate } from "../src/db.js";

const url = process.env.TEST_DATABASE_URL ?? "postgres://ble:ble@127.0.0.1:5432/ble_test";
const db = new pg.Pool({ connectionString: url, max: 4 });
const fixture = (): RunExport => {
  const r = JSON.parse(readFileSync(new URL("./fixtures/run_X01.json", import.meta.url), "utf8")) as RunExport;
  r.findings.find((x) => x.type === "reservation")!.needs_review = true;
  return r;
};

beforeEach(async () => {
  await db.query("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;");
  await migrate(db);
});
afterAll(async () => db.end());

const keys = { v: "viewer", r: "reviewer", w: "worker" } as const;
const H = (k: string) => ({ "x-api-key": k });

describe("auth", () => {
  it("needs a key with the right role when keys are configured", async () => {
    const app = buildApp(db, { apiKeys: keys });
    expect((await app.inject({ method: "GET", url: "/api/tenders" })).statusCode).toBe(401);
    expect((await app.inject({ method: "GET", url: "/api/tenders", headers: H("nope") })).statusCode).toBe(401);
    expect((await app.inject({ method: "GET", url: "/api/tenders", headers: H("v") })).statusCode).toBe(200);
    expect((await app.inject({ method: "POST", url: "/api/runs", headers: H("r"), payload: fixture() })).statusCode).toBe(403);
    expect((await app.inject({ method: "POST", url: "/api/runs", headers: H("w"), payload: fixture() })).statusCode).toBe(201);
    expect((await app.inject({ method: "GET", url: "/health" })).json().auth).toBe("api keys");
  });

  it("rejects something that is not a run export", async () => {
    const app = buildApp(db);
    expect((await app.inject({ method: "POST", url: "/api/runs", payload: { hello: 1 } })).statusCode).toBe(400);
  });
});

describe("runs and review", () => {
  it("stores a run and serves the tender, sheet and findings", async () => {
    const app = buildApp(db);
    const res = (await app.inject({ method: "POST", url: "/api/runs", payload: fixture() })).json();
    expect(res).toMatchObject({ tender_id: "X01", bids: 3, findings: 2, decisions_carried_over: 0 });
    const list = (await app.inject({ method: "GET", url: "/api/tenders" })).json();
    expect(list).toEqual([expect.objectContaining({ id: "X01", bids: 3, openFindings: 2 })]);
    const t = (await app.inject({ method: "GET", url: "/api/tenders/X01" })).json();
    expect(t.bids.map((b: { rank: number }) => b.rank)).toEqual([1, 2, 3]);
    const sheet = (await app.inject({ method: "GET", url: "/api/tenders/X01/sheet" })).json();
    expect(sheet.cells["01.0010"]["X01-B1"].flags).toEqual(["missing_price"]);
    expect(sheet.trades["03"]).toBe("Beton");
    const fs = (await app.inject({ method: "GET", url: "/api/tenders/X01/findings?type=missing_price" })).json();
    expect(fs).toHaveLength(1);
    expect(fs[0].detail).toHaveProperty("expected");
    expect((await app.inject({ method: "GET", url: "/api/tenders/NOPE/sheet" })).statusCode).toBe(404);
  });

  it("records decisions, takes rejected findings out of the sheet and export, and keeps decisions across re-runs", async () => {
    const app = buildApp(db);
    await app.inject({ method: "POST", url: "/api/runs", payload: fixture() });
    const queue = (await app.inject({ method: "GET", url: "/api/review-queue" })).json();
    expect(queue.map((x: { type: string }) => x.type)).toEqual(["reservation"]);
    const mp = (await app.inject({ method: "GET", url: "/api/tenders/X01/findings?type=missing_price" })).json()[0];

    expect((await app.inject({ method: "POST", url: `/api/findings/${mp.id}/decision`, payload: { verdict: "maybe" } })).statusCode).toBe(400);
    expect((await app.inject({ method: "POST", url: "/api/findings/nope/decision", payload: { verdict: "rejected" } })).statusCode).toBe(404);
    const d = await app.inject({ method: "POST", url: `/api/findings/${mp.id}/decision`, payload: { verdict: "rejected", note: "Price is in 01.0020", reviewer: "ak" } });
    expect(d.statusCode).toBe(201);

    const sheet = (await app.inject({ method: "GET", url: "/api/tenders/X01/sheet" })).json();
    expect(sheet.cells["01.0010"]["X01-B1"].flags).toEqual([]);
    const exp = (await app.inject({ method: "GET", url: "/api/tenders/X01/export" })).json();
    expect(exp.findings.map((x: { type: string }) => x.type)).toEqual(["reservation"]);
    expect(exp.findings[0].status).toBe("open");

    const again = (await app.inject({ method: "POST", url: "/api/runs", payload: { ...fixture(), run_id: "fixture0002" } })).json();
    expect(again.decisions_carried_over).toBe(1);
    const after = (await app.inject({ method: "GET", url: `/api/findings/${mp.id}` })).json();
    expect(after.status).toBe("rejected");
    expect(after.decisions).toHaveLength(1);
    expect((await app.inject({ method: "GET", url: "/api/decisions?tender=X01" })).json()).toHaveLength(1);
    const metrics = (await app.inject({ method: "GET", url: "/metrics" })).body;
    expect(metrics).toContain('ble_review_decisions_total{verdict="rejected",type="missing_price"} 1');
    expect(metrics).toContain("ble_findings_open 1");
  });

  it("rolls back a run that fails to store", async () => {
    const app = buildApp(db);
    await app.inject({ method: "POST", url: "/api/runs", payload: fixture() });
    const bad = fixture();
    bad.findings.push({ ...bad.findings[0] }); // duplicate finding id
    await expect(storeRun(db, bad)).rejects.toThrow();
    const list = (await app.inject({ method: "GET", url: "/api/tenders" })).json();
    expect(list[0].openFindings).toBe(2); // the earlier run is still there
  });
});

describe("AI service proxy", () => {
  it("passes chat to the AI service and keeps the turn", async () => {
    const calls: { url: string; body: string }[] = [];
    const fetchImpl = (async (u: string | URL, init?: RequestInit) => {
      calls.push({ url: String(u), body: String(init?.body) });
      return new Response(JSON.stringify({ intent: "ranking", text: "1. Hoffmann [E1]", citations: [{ ref: "E1" }] }), { status: 200 });
    }) as typeof fetch;
    const app = buildApp(db, { aiUrl: "http://ai.test", fetchImpl });
    await app.inject({ method: "POST", url: "/api/runs", payload: fixture() });
    const r = await app.inject({ method: "POST", url: "/api/tenders/X01/chat", payload: { question: "Who is cheapest?" } });
    expect(r.statusCode).toBe(200);
    expect(r.json().intent).toBe("ranking");
    expect(calls[0].url).toBe("http://ai.test/chat");
    expect(JSON.parse(calls[0].body)).toEqual({ tender_id: "X01", question: "Who is cheapest?" });
    expect((await db.query("SELECT count(*)::int AS n FROM chat_turn")).rows[0].n).toBe(1);
    expect((await app.inject({ method: "POST", url: "/api/tenders/X01/chat", payload: { question: "?" } })).statusCode).toBe(400);
    expect((await app.inject({ method: "POST", url: "/api/tenders/NOPE/chat", payload: { question: "Who?" } })).statusCode).toBe(404);
  });

  it("reports an AI service failure as 502", async () => {
    const app = buildApp(db, { fetchImpl: (async () => new Response("x", { status: 500 })) as typeof fetch });
    await app.inject({ method: "POST", url: "/api/runs", payload: fixture() });
    expect((await app.inject({ method: "POST", url: "/api/tenders/X01/chat", payload: { question: "Who is cheapest?" } })).statusCode).toBe(502);
  });

  it("validates evidence references and passes 409 for a changed document", async () => {
    let status = 200;
    const seen: string[] = [];
    const fetchImpl = (async (u: string | URL) => {
      seen.push(String(u));
      return new Response(status === 200 ? new Uint8Array([137, 80, 78, 71]) : "changed", { status });
    }) as typeof fetch;
    const app = buildApp(db, { aiUrl: "http://ai.test", fetchImpl });
    const ok = await app.inject({ method: "GET", url: "/api/evidence?doc=X01/bids/a.pdf@abc123&page=1&bbox=1,2,3,4" });
    expect(ok.statusCode).toBe(200);
    expect(ok.headers["content-type"]).toBe("image/png");
    expect(new URL(seen[0]).searchParams.get("doc")).toBe("X01/bids/a.pdf@abc123");
    expect((await app.inject({ method: "GET", url: "/api/evidence?doc=a.pdf;rm&page=1" })).statusCode).toBe(400);
    expect((await app.inject({ method: "GET", url: "/api/evidence?doc=a.pdf@1&bbox=1,2);x" })).statusCode).toBe(400);
    status = 409;
    expect((await app.inject({ method: "GET", url: "/api/evidence?doc=a.pdf@1" })).statusCode).toBe(409);
  });

  it("serves the review UI", async () => {
    const app = buildApp(db);
    const r = await app.inject({ method: "GET", url: "/" });
    expect(r.statusCode).toBe(200);
    expect(r.body).toContain("Leveling sheet");
    expect((await app.inject({ method: "GET", url: "/app.js" })).headers["content-type"]).toContain("javascript");
  });
});
