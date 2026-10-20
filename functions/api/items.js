import { json, authed, db, profileOf, storeKey } from "../../lib/zia.js";

const KEYS = ["items", "chat", "images"];
const LIMITS = { items: [0, 2000], chat: [-100], images: [0, 500] };
const MAX_ROW = 1_900_000; // D1 row limit is 2 MB

export async function onRequestGet({ request, env }) {
  if (!authed(request, env)) return json({ error: "locked" }, 401);
  const u = profileOf(request);
  if (u === null) return json({ error: "unknown profile" }, 404);
  try {
    const { results } = await (await db(env)).prepare("SELECT k, v FROM store WHERE k IN (?1, ?2, ?3)").bind(...KEYS.map(k => storeKey(u, k))).all();
    const out = { items: [], chat: [], images: [] };
    for (const r of results) { const k = KEYS.find(k => storeKey(u, k) === r.k); if (k) out[k] = JSON.parse(r.v); }
    return json(out);
  } catch (e) { return json({ error: e.message }, e.status || 500); }
}

export async function onRequestPut({ request, env }) {
  if (!authed(request, env)) return json({ error: "locked" }, 401);
  const u = profileOf(request);
  if (u === null) return json({ error: "unknown profile" }, 404);
  let body;
  try { body = await request.json(); } catch (e) { return json({ error: "bad json" }, 400); }
  const rows = KEYS.map(k => {
    const list = (Array.isArray(body[k]) ? body[k] : []).filter(o => o && typeof o === "object");
    return [storeKey(u, k), JSON.stringify(list.slice(...LIMITS[k]))];
  });
  const big = rows.find(([, v]) => v.length > MAX_ROW);
  if (big) return json({ error: `${big[0]} is too large to save` }, 413);
  try {
    const d = await db(env);
    const st = d.prepare("INSERT INTO store (k, v) VALUES (?1, ?2) ON CONFLICT(k) DO UPDATE SET v = excluded.v");
    await d.batch(rows.map(([k, v]) => st.bind(k, v)));
    return json({ ok: true });
  } catch (e) { return json({ error: e.message }, e.status || 500); }
}
