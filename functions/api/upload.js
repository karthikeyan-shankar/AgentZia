import { json, authed, db, randomHex, IMAGE_TYPES, MAX_IMAGE } from "../../lib/zia.js";

export async function onRequestPost({ request, env }) {
  if (!authed(request, env)) return json({ error: "locked" }, 401);
  const type = (request.headers.get("Content-Type") || "").split(";")[0].trim().toLowerCase();
  if (!IMAGE_TYPES[type]) return json({ error: "send a JPEG, PNG or WebP" }, 400);
  const buf = await request.arrayBuffer();
  if (!buf.byteLength || buf.byteLength > MAX_IMAGE) return json({ error: "image must be under 1.9 MB" }, 413);
  try {
    // random 24-hex-char names can't be guessed or used to reach anything else
    const name = randomHex(12) + IMAGE_TYPES[type];
    await (await db(env)).prepare("INSERT INTO images (name, type, data, created) VALUES (?1, ?2, ?3, ?4)")
      .bind(name, type, buf, Date.now()).run();
    return json({ url: "/uploads/" + name });
  } catch (e) { return json({ error: e.message }, e.status || 500); }
}
