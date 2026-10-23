import { migrate, pool } from "./db.js";

const db = pool();
const applied = await migrate(db);
console.log(applied.length ? `applied: ${applied.join(", ")}` : "up to date");
await db.end();
