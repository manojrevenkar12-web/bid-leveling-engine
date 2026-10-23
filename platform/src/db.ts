// Postgres access: a pool, SQL migrations applied in order, and a transaction helper.
import { readdir, readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import pg from "pg";

export type Db = pg.Pool;
export type Tx = pg.PoolClient;

const SQL = join(dirname(fileURLToPath(import.meta.url)), "..", "sql");

export function pool(url = process.env.DATABASE_URL): Db {
  if (!url) throw new Error("DATABASE_URL is not set");
  return new pg.Pool({ connectionString: url, max: 10 });
}

export async function migrate(db: Db): Promise<string[]> {
  await db.query("CREATE TABLE IF NOT EXISTS schema_migration (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())");
  const done = new Set((await db.query<{ name: string }>("SELECT name FROM schema_migration")).rows.map((r) => r.name));
  const applied: string[] = [];
  for (const f of (await readdir(SQL)).filter((x) => x.endsWith(".sql")).sort()) {
    if (done.has(f)) continue;
    await tx(db, async (c) => {
      await c.query(await readFile(join(SQL, f), "utf8"));
      await c.query("INSERT INTO schema_migration(name) VALUES ($1)", [f]);
    });
    applied.push(f);
  }
  return applied;
}

export async function tx<T>(db: Db, fn: (c: Tx) => Promise<T>): Promise<T> {
  const c = await db.connect();
  try {
    await c.query("BEGIN");
    const out = await fn(c);
    await c.query("COMMIT");
    return out;
  } catch (e) {
    await c.query("ROLLBACK");
    throw e;
  } finally {
    c.release();
  }
}
