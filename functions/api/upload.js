import { json, authed, db, randomHex, FILE_TYPES, MAX_FILE, CHUNK } from "../../lib/zia.js";

export async function onRequestPost({ request, env }) {
  if (!authed(request, env)) return json({ error: "locked" }, 401);
  const type = (request.headers.get("Content-Type") || "").split(";")[0].trim().toLowerCase();
  if (!FILE_TYPES[type]) return json({ error: "send a photo (JPEG, PNG, WebP) or a PDF" }, 400);
  const buf = await request.arrayBuffer();
  if (!buf.byteLength || buf.byteLength > MAX_FILE) return json({ error: "file must be under 20 MB" }, 413);
  try {
    // random 24-hex-char names can't be guessed or used to reach anything else
    const name = randomHex(12) + FILE_TYPES[type], d = await db(env), n = Math.ceil(buf.byteLength / CHUNK);
    for (let i = 0; i < n; i++) {
      await d.prepare("INSERT INTO blobs (name, idx, data) VALUES (?1, ?2, ?3)").bind(name, i, buf.slice(i * CHUNK, (i + 1) * CHUNK)).run();
    }
    // the index row goes in last, so a half-finished upload is never served
    await d.prepare("INSERT INTO files (name, type, size, chunks, created) VALUES (?1, ?2, ?3, ?4, ?5)").bind(name, type, buf.byteLength, n, Date.now()).run();
    return json({ url: "/uploads/" + name });
  } catch (e) { return json({ error: e.message }, e.status || 500); }
}
