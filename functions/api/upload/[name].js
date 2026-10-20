import { json, authed, db, FILE_NAME } from "../../../lib/zia.js";

export async function onRequestDelete({ request, env, params }) {
  const name = String(params.name);
  if (!FILE_NAME.test(name)) return json({ error: "not found" }, 404);
  if (!authed(request, env)) return json({ error: "locked" }, 401);
  try {
    const d = await db(env);
    await d.batch([
      d.prepare("DELETE FROM files WHERE name = ?1").bind(name),
      d.prepare("DELETE FROM blobs WHERE name = ?1").bind(name),
      d.prepare("DELETE FROM images WHERE name = ?1").bind(name)
    ]);
    return json({ ok: true });
  } catch (e) { return json({ error: e.message }, e.status || 500); }
}
