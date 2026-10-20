import { db, IMAGE_NAME } from "../../lib/zia.js";

export async function onRequestGet({ env, params }) {
  const name = String(params.name);
  if (!IMAGE_NAME.test(name)) return new Response("Not found", { status: 404 });
  const row = await (await db(env)).prepare("SELECT type, data FROM images WHERE name = ?1").bind(name).first();
  if (!row) return new Response("Not found", { status: 404 });
  return new Response(new Uint8Array(row.data), {
    headers: { "Content-Type": row.type, "Cache-Control": "private, max-age=31536000, immutable" }
  });
}
