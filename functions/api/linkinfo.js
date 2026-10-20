import { json, authed, parseMeta } from "../../lib/zia.js";

// GET /api/linkinfo?url=... -> { title, image, description } for link cards on the board
export async function onRequestGet({ request, env }) {
  if (!authed(request, env)) return json({ error: "locked" }, 401);
  let u;
  try { u = new URL(new URL(request.url).searchParams.get("url") || ""); } catch (e) { return json({ error: "bad url" }, 400); }
  if (!/^https?:$/.test(u.protocol)) return json({ error: "bad url" }, 400);
  try {
    const r = await fetch(u.href, { headers: { "User-Agent": "Mozilla/5.0 (compatible; ZiaLinkPreview/1.0)", Accept: "text/html,*/*" }, redirect: "follow" });
    const type = r.headers.get("content-type") || "";
    if (!type.includes("html")) return json({ title: "", image: type.startsWith("image/") && u.protocol === "https:" ? u.href : "", description: "" });
    return json(parseMeta((await r.text()).slice(0, 400000), r.url || u.href));
  } catch (e) { return json({ title: "", image: "", description: "" }); }
}
