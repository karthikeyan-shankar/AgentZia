import { db, FILE_NAME } from "../../lib/zia.js";

export async function onRequestGet({ env, params }) {
  const name = String(params.name);
  if (!FILE_NAME.test(name)) return new Response("Not found", { status: 404 });
  const d = await db(env), cache = "private, max-age=31536000, immutable";
  const f = await d.prepare("SELECT type, size, chunks FROM files WHERE name = ?1").bind(name).first();
  if (f) {
    const out = new Uint8Array(f.size);
    let at = 0;
    for (let i = 0; i < f.chunks; i++) {
      const row = await d.prepare("SELECT data FROM blobs WHERE name = ?1 AND idx = ?2").bind(name, i).first();
      if (!row) return new Response("Not found", { status: 404 });
      const part = new Uint8Array(row.data);
      out.set(part, at); at += part.length;
    }
    const headers = { "Content-Type": f.type, "Cache-Control": cache };
    if (f.type === "application/pdf") headers["Content-Disposition"] = `inline; filename="${name}"`;
    return new Response(out, { headers });
  }
  const old = await d.prepare("SELECT type, data FROM images WHERE name = ?1").bind(name).first(); // photos saved before chunking
  if (!old) return new Response("Not found", { status: 404 });
  return new Response(new Uint8Array(old.data), { headers: { "Content-Type": old.type, "Cache-Control": cache } });
}
