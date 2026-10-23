// The platform API: stores tender runs published by the Python workflows, serves the leveling
// sheet and findings with their evidence, records review decisions (which carry over to later runs
// of the same tender), and proxies chat and evidence images to the AI service.
import { readFile } from "node:fs/promises";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import Fastify, { type FastifyInstance, type FastifyReply, type FastifyRequest } from "fastify";
import { type Db, tx } from "./db.js";

export type Role = "viewer" | "reviewer" | "worker";
const RANK: Record<Role, number> = { viewer: 0, reviewer: 1, worker: 2 };

export interface Options {
  apiKeys?: Record<string, Role>; // empty = open (local development)
  aiUrl?: string; // the Python AI service
  fetchImpl?: typeof fetch;
}

const here = dirname(fileURLToPath(import.meta.url));
const PUBLIC = join(here, "..", "public");

function parseKeys(raw: string | undefined): Record<string, Role> {
  const out: Record<string, Role> = {};
  for (const part of (raw ?? "").split(",").map((s) => s.trim()).filter(Boolean)) {
    const [k, r] = part.split(":");
    out[k] = (["viewer", "reviewer", "worker"].includes(r) ? r : "viewer") as Role;
  }
  return out;
}

export function keysFromEnv(): Record<string, Role> {
  return parseKeys(process.env.PLATFORM_API_KEYS);
}

class Metrics {
  counters = new Map<string, number>();
  inc(name: string, labels: Record<string, string> = {}, by = 1) {
    const k = `${name}${Object.keys(labels).length ? "{" + Object.entries(labels).map(([a, b]) => `${a}="${b}"`).join(",") + "}" : ""}`;
    this.counters.set(k, (this.counters.get(k) ?? 0) + by);
  }
  text(): string {
    return [...this.counters.entries()].map(([k, v]) => `${k} ${v}`).join("\n") + "\n";
  }
}

const VERDICTS = new Set(["confirmed", "rejected"]);

export function buildApp(db: Db, opts: Options = {}): FastifyInstance {
  const app = Fastify({ logger: false, bodyLimit: 20 * 1024 * 1024 });
  const keys = opts.apiKeys ?? {};
  const open = Object.keys(keys).length === 0;
  const f = opts.fetchImpl ?? fetch;
  const ai = opts.aiUrl ?? process.env.AI_SERVICE_URL ?? "http://127.0.0.1:8001";
  const metrics = new Metrics();

  function role(req: FastifyRequest): Role | null {
    if (open) return "worker";
    const k = req.headers["x-api-key"];
    return typeof k === "string" && keys[k] ? keys[k] : null;
  }
  const need = (min: Role) => async (req: FastifyRequest, reply: FastifyReply) => {
    const r = role(req);
    if (!r) return reply.code(401).send({ error: "missing or unknown X-API-Key" });
    if (RANK[r] < RANK[min]) return reply.code(403).send({ error: `needs the ${min} role` });
  };

  app.addHook("onResponse", async (req, reply) => {
    metrics.inc("ble_http_requests_total", { route: req.routeOptions.url ?? "unknown", status: String(reply.statusCode) });
  });

  app.get("/health", async () => ({ ok: true, auth: open ? "open (set PLATFORM_API_KEYS)" : "api keys" }));
  app.get("/metrics", async (_req, reply) => {
    const open_ = (await db.query("SELECT count(*)::int AS n FROM finding WHERE status = 'open'")).rows[0].n;
    reply.type("text/plain; version=0.0.4");
    return metrics.text() + `ble_findings_open ${open_}\n`;
  });

  // -- runs published by the workflows ------------------------------------------------------------
  app.post("/api/runs", { preHandler: need("worker") }, async (req, reply) => {
    const run = req.body as RunExport;
    if (!run || typeof run.tender_id !== "string" || !Array.isArray(run.bids) || !Array.isArray(run.findings)) {
      return reply.code(400).send({ error: "not a run export" });
    }
    const res = await storeRun(db, run);
    metrics.inc("ble_runs_published_total");
    return reply.code(201).send(res);
  });

  // -- reading -------------------------------------------------------------------------------------
  app.get("/api/tenders", { preHandler: need("viewer") }, async () => {
    const r = await db.query(`
      SELECT t.id, t.project, t.latest_version AS "latestVersion", t.updated_at AS "updatedAt",
             (SELECT count(*)::int FROM bid b WHERE b.tender_id = t.id) AS bids,
             (SELECT count(*)::int FROM finding f WHERE f.tender_id = t.id AND f.status = 'open') AS "openFindings"
      FROM tender t ORDER BY t.id`);
    return r.rows;
  });

  app.get<{ Params: { id: string } }>("/api/tenders/:id", { preHandler: need("viewer") }, async (req, reply) => {
    const t = (await db.query('SELECT id, project, latest_version AS "latestVersion", run_id AS "runId" FROM tender WHERE id = $1', [req.params.id])).rows[0];
    if (!t) return reply.code(404).send({ error: "no such tender" });
    const versions = (await db.query("SELECT version, date, label FROM boq_version WHERE tender_id = $1 ORDER BY version", [t.id])).rows;
    const bids = (
      await db.query(
        `SELECT b.id, b.company, b.route, b.priced_version AS "pricedVersion", b.stated_total AS "statedTotal", b.comparable_total AS "comparableTotal",
                b.rank, b.stated_rank AS "statedRank", b.pages, b.cost_eur AS "costEur",
                coalesce((SELECT jsonb_object_agg(status, n) FROM (SELECT status, count(*)::int AS n FROM finding f WHERE f.bid_id = b.id GROUP BY status) s), '{}') AS findings
         FROM bid b WHERE b.tender_id = $1 ORDER BY b.rank NULLS LAST, b.id`,
        [t.id],
      )
    ).rows;
    return { ...t, versions, bids };
  });

  app.get<{ Params: { id: string } }>("/api/tenders/:id/sheet", { preHandler: need("viewer") }, async (req, reply) => {
    const t = (await db.query("SELECT export FROM tender WHERE id = $1", [req.params.id])).rows[0];
    if (!t) return reply.code(404).send({ error: "no such tender" });
    const exp = t.export as RunExport;
    const rejected = await rejectedKeys(req.params.id, exp);
    // the sheet's cell flags respect review: a rejected finding no longer flags its cell
    const cells = Object.fromEntries(
      Object.entries(exp.sheet.cells).map(([oz, row]) => [
        oz,
        Object.fromEntries(Object.entries(row).map(([bid, c]) => [bid, { ...c, flags: c.flags.filter((fl: string) => !rejected.has(`${bid}|${oz}|${fl}`)) }])),
      ]),
    );
    return { ...exp.sheet, cells, trades: exp.trades ?? {} };
  });

  async function statuses(tenderId: string): Promise<Map<string, string>> {
    const r = await db.query<{ id: string; status: string }>("SELECT id, status FROM finding WHERE tender_id = $1", [tenderId]);
    return new Map(r.rows.map((x) => [x.id, x.status]));
  }
  async function rejectedKeys(tenderId: string, exp: RunExport): Promise<Set<string>> {
    const s = await statuses(tenderId);
    return new Set(exp.findings.filter((x) => s.get(x.id) === "rejected").map((x) => `${x.bid_id}|${x.oz}|${x.type}`));
  }

  app.get<{ Params: { id: string } }>("/api/tenders/:id/export", { preHandler: need("viewer") }, async (req, reply) => {
    const t = (await db.query("SELECT export FROM tender WHERE id = $1", [req.params.id])).rows[0];
    if (!t) return reply.code(404).send({ error: "no such tender" });
    const exp = t.export as RunExport;
    const s = await statuses(req.params.id);
    // what the AI service sees: findings people rejected are gone, the rest carry their review status
    return { ...exp, findings: exp.findings.filter((x) => s.get(x.id) !== "rejected").map((x) => ({ ...x, status: s.get(x.id) ?? "open" })) };
  });

  const FINDING_COLS = `id, tender_id AS "tenderId", bid_id AS "bidId", type, oz, severity, message, confidence, needs_review AS "needsReview", status, evidence, detail, run_id AS "runId"`;

  app.get<{ Params: { id: string }; Querystring: { bid?: string; type?: string; status?: string; review?: string } }>(
    "/api/tenders/:id/findings",
    { preHandler: need("viewer") },
    async (req) => {
      const q = req.query;
      const where = ["tender_id = $1"];
      const args: unknown[] = [req.params.id];
      for (const [col, v] of [["bid_id", q.bid], ["type", q.type], ["status", q.status]] as const) {
        if (v) {
          args.push(v);
          where.push(`${col} = $${args.length}`);
        }
      }
      if (q.review === "1") where.push("needs_review");
      return (await db.query(`SELECT ${FINDING_COLS} FROM finding WHERE ${where.join(" AND ")} ORDER BY bid_id, oz NULLS FIRST, type`, args)).rows;
    },
  );

  app.get("/api/review-queue", { preHandler: need("viewer") }, async () =>
    (await db.query(`SELECT ${FINDING_COLS} FROM finding WHERE status = 'open' AND needs_review ORDER BY confidence, id LIMIT 200`)).rows,
  );

  app.get<{ Params: { id: string } }>("/api/findings/:id", { preHandler: need("viewer") }, async (req, reply) => {
    const x = (await db.query(`SELECT ${FINDING_COLS} FROM finding WHERE id = $1`, [req.params.id])).rows[0];
    if (!x) return reply.code(404).send({ error: "no such finding" });
    const decisions = (await db.query('SELECT id, verdict, note, reviewer, created_at AS "createdAt" FROM decision WHERE finding_id = $1 ORDER BY created_at', [x.id])).rows;
    return { ...x, decisions };
  });

  // -- review ----------------------------------------------------------------------------------------
  app.post<{ Params: { id: string }; Body: { verdict?: string; note?: string; reviewer?: string } }>(
    "/api/findings/:id/decision",
    { preHandler: need("reviewer") },
    async (req, reply) => {
      const { verdict, note, reviewer } = req.body ?? {};
      if (!verdict || !VERDICTS.has(verdict)) return reply.code(400).send({ error: "verdict must be confirmed or rejected" });
      if (note && note.length > 2000) return reply.code(400).send({ error: "note too long" });
      const x = (await db.query("SELECT id, tender_id, type FROM finding WHERE id = $1", [req.params.id])).rows[0];
      if (!x) return reply.code(404).send({ error: "no such finding" });
      const d = await tx(db, async (c) => {
        const r = await c.query(
          'INSERT INTO decision(finding_id, tender_id, verdict, note, reviewer) VALUES ($1, $2, $3, $4, $5) RETURNING id, finding_id AS "findingId", verdict, note, reviewer, created_at AS "createdAt"',
          [x.id, x.tender_id, verdict, note ?? null, reviewer ?? "reviewer"],
        );
        await c.query("UPDATE finding SET status = $2 WHERE id = $1", [x.id, verdict]);
        return r.rows[0];
      });
      metrics.inc("ble_review_decisions_total", { verdict, type: x.type });
      return reply.code(201).send(d);
    },
  );

  app.get<{ Querystring: { tender?: string } }>("/api/decisions", { preHandler: need("viewer") }, async (req) => {
    const sql = 'SELECT id, finding_id AS "findingId", tender_id AS "tenderId", verdict, note, reviewer, created_at AS "createdAt" FROM decision';
    const r = req.query.tender ? await db.query(`${sql} WHERE tender_id = $1 ORDER BY created_at`, [req.query.tender]) : await db.query(`${sql} ORDER BY created_at`);
    return r.rows;
  });

  // -- AI service --------------------------------------------------------------------------------------
  app.post<{ Params: { id: string }; Body: { question?: string } }>("/api/tenders/:id/chat", { preHandler: need("reviewer") }, async (req, reply) => {
    const question = (req.body?.question ?? "").trim();
    if (question.length < 2 || question.length > 500) return reply.code(400).send({ error: "question must be 2 to 500 characters" });
    const t = (await db.query("SELECT id FROM tender WHERE id = $1", [req.params.id])).rows[0];
    if (!t) return reply.code(404).send({ error: "no such tender" });
    const r = await f(`${ai}/chat`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ tender_id: t.id, question }) });
    if (!r.ok) return reply.code(502).send({ error: `AI service: ${r.status}` });
    const answer = await r.json();
    await db.query("INSERT INTO chat_turn(tender_id, question, answer) VALUES ($1, $2, $3)", [t.id, question, answer]);
    metrics.inc("ble_chat_turns_total");
    return answer;
  });

  app.get<{ Querystring: { doc?: string; page?: string; bbox?: string } }>("/api/evidence", { preHandler: need("viewer") }, async (req, reply) => {
    const { doc, page, bbox } = req.query;
    if (!doc || !/^[\w./@-]+$/.test(doc) || (bbox && !/^[\d.,]+$/.test(bbox)) || (page && !/^\d+$/.test(page))) return reply.code(400).send({ error: "bad evidence reference" });
    const u = new URL(`${ai}/evidence.png`);
    u.searchParams.set("doc", doc);
    if (page) u.searchParams.set("page", page);
    if (bbox) u.searchParams.set("bbox", bbox);
    const r = await f(u);
    if (!r.ok) return reply.code(r.status === 409 ? 409 : 502).send({ error: `evidence: ${r.status}` });
    reply.type("image/png");
    return Buffer.from(await r.arrayBuffer());
  });

  // -- the review UI ---------------------------------------------------------------------------------
  const files: Record<string, string> = { "/": "index.html", "/app.js": "app.js", "/styles.css": "styles.css" };
  for (const [route, file] of Object.entries(files)) {
    app.get(route, async (_req, reply) => {
      const body = await readFile(join(PUBLIC, file));
      reply.type(file.endsWith(".js") ? "text/javascript" : file.endsWith(".css") ? "text/css" : "text/html; charset=utf-8");
      return body;
    });
  }
  return app;
}

// -- storing a run --------------------------------------------------------------------------------------
export interface RunExport {
  tender_id: string;
  project: string;
  run_id: string;
  versions: { version: string; date: string; label: string; doc_id: string; positions: { oz: string; trade: string; short: string; long: string; qty: number | null; unit: string; evidence: unknown }[] }[];
  bids: {
    bid_id: string;
    company: string;
    route: string;
    pages: number;
    cost_eur: number;
    stated_total: number | null;
    priced_version: string;
    lines: { idx: number; shown_no: string; short: string; qty: number | null; unit: string; ep: number | null; gp: number | null; oz: string | null; match_p: number; match_needs_review: boolean; evidence: unknown }[];
  }[];
  findings: { id: string; bid_id: string; type: string; oz: string | null; severity: string; message: string; confidence: number; needs_review: boolean; evidence: unknown[]; detail: Record<string, unknown>; expected?: unknown; found?: unknown }[];
  trades?: Record<string, string>;
  sheet: { ranking: { bid_id: string; rank: number; stated_rank: number; comparable_total: number }[]; bidders: { bid_id: string; comparable_total: number }[]; cells: Record<string, Record<string, { flags: string[] } & Record<string, unknown>>> };
  traces: { trace_id: string; code_version: string; config_version: string }[];
}

export async function storeRun(db: Db, run: RunExport) {
  const latest = run.versions[run.versions.length - 1];
  const rank = new Map(run.sheet.ranking.map((r) => [r.bid_id, r]));
  const j = (x: unknown) => JSON.stringify(x);
  return tx(db, async (c) => {
    const prior = await c.query<{ finding_id: string; verdict: string }>("SELECT DISTINCT ON (finding_id) finding_id, verdict FROM decision WHERE tender_id = $1 ORDER BY finding_id, created_at DESC", [run.tender_id]);
    const lastVerdict = new Map(prior.rows.map((d) => [d.finding_id, d.verdict]));
    await c.query("DELETE FROM tender WHERE id = $1", [run.tender_id]); // cascades; decisions are kept
    await c.query("INSERT INTO tender(id, project, latest_version, run_id, export) VALUES ($1, $2, $3, $4, $5)", [run.tender_id, run.project, latest.version, run.run_id, j(run)]);
    for (const v of run.versions) {
      const vid = `${run.tender_id}/${v.version}`;
      await c.query("INSERT INTO boq_version(id, tender_id, version, date, label, doc_id) VALUES ($1, $2, $3, $4, $5, $6)", [vid, run.tender_id, v.version, v.date, v.label, v.doc_id]);
      for (const p of v.positions) {
        await c.query("INSERT INTO position(id, version_id, oz, trade, short, long, qty, unit, evidence) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)", [
          `${vid}/${p.oz}`, vid, p.oz, p.trade, p.short, p.long, p.qty, p.unit, j(p.evidence),
        ]);
      }
    }
    for (const b of run.bids) {
      const r = rank.get(b.bid_id);
      await c.query(
        "INSERT INTO bid(id, tender_id, company, route, priced_version, stated_total, comparable_total, rank, stated_rank, pages, cost_eur) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
        [b.bid_id, run.tender_id, b.company, b.route, b.priced_version, b.stated_total, r?.comparable_total ?? null, r?.rank ?? null, r?.stated_rank ?? null, b.pages, b.cost_eur],
      );
      for (const l of b.lines) {
        await c.query("INSERT INTO bid_line(id, bid_id, idx, shown_no, short, qty, unit, ep, gp, oz, match_p, needs_review, evidence) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)", [
          `${b.bid_id}/${l.idx}`, b.bid_id, l.idx, l.shown_no, l.short, l.qty, l.unit, l.ep, l.gp, l.oz, l.match_p, l.match_needs_review, j(l.evidence),
        ]);
      }
    }
    for (const x of run.findings) {
      await c.query("INSERT INTO finding(id, tender_id, bid_id, type, oz, severity, message, confidence, needs_review, status, evidence, detail, run_id) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)", [
        x.id, run.tender_id, x.bid_id, x.type, x.oz, x.severity, x.message, x.confidence, x.needs_review, lastVerdict.get(x.id) ?? "open", j(x.evidence), j({ ...x.detail, expected: x.expected ?? null, found: x.found ?? null }), run.run_id,
      ]);
    }
    const t0 = run.traces[0];
    await c.query("INSERT INTO run(id, tender_id, code_version, config_version, traces) VALUES ($1, $2, $3, $4, $5)", [run.run_id, run.tender_id, t0?.code_version ?? "", t0?.config_version ?? "", j(run.traces)]);
    const carried = run.findings.filter((x) => lastVerdict.has(x.id)).length;
    return { tender_id: run.tender_id, run_id: run.run_id, bids: run.bids.length, findings: run.findings.length, decisions_carried_over: carried };
  });
}
