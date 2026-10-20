import { json, authed, db, IMAGE_NAME } from "../../../lib/zia.js";

export async function onRequestDelete({ request, env, params }) {
  const name = String(params.name);
  if (!IMAGE_NAME.test(name)) return json({ error: "not found" }, 404);
  if (!authed(request, env)) return json({ error: "locked" }, 401);
  try {
    await (await db(env)).prepare("DELETE FROM images WHERE name = ?1").bind(name).run();
    return json({ ok: true });
  } catch (e) { return json({ error: e.message }, e.status || 500); }
}
