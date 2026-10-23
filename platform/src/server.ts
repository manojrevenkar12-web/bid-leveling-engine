import { buildApp, keysFromEnv } from "./app.js";
import { migrate, pool } from "./db.js";

const db = pool();
const applied = await migrate(db);
if (applied.length) console.log(`applied migrations: ${applied.join(", ")}`);
const app = buildApp(db, { apiKeys: keysFromEnv() });
const port = Number(process.env.PORT ?? 3000);
const host = process.env.HOST ?? "127.0.0.1";
await app.listen({ port, host });
console.log(`platform on http://${host}:${port}`);
for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, async () => {
    await app.close();
    await db.end();
    process.exit(0);
  });
}
