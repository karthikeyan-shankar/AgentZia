import { json, authed, askGroq, profileOf } from "../../lib/zia.js";

export async function onRequestPost({ request, env }) {
  if (!authed(request, env)) return json({ error: "locked" }, 401);
  const u = profileOf(request);
  if (u === null) return json({ error: "unknown profile" }, 404);
  if (!env.GROQ_API_KEY) return json({ error: "GROQ_API_KEY is not set" }, 503);
  try {
    const b = await request.json();
    const items = (Array.isArray(b.items) ? b.items : []).filter(o => o && typeof o === "object").slice(0, 300);
    const history = Array.isArray(b.history) ? b.history : [];
    return json(await askGroq(env, String(b.said || "").slice(0, 600), items, String(b.today || ""), history, u));
  } catch (e) {
    return json({ error: e.status ? e.message : "chat failed" }, e.status || 500);
  }
}
