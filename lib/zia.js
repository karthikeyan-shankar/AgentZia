// Shared code for Zia's Cloudflare Pages Functions (the online version of krefter_server.py).
// Bindings/settings (Cloudflare dashboard -> Pages project -> Settings):
//   DB             D1 database binding (required: tasks, chat and images live here)
//   GROQ_API_KEY   secret, for AI replies
//   GROQ_MODEL     optional, default openai/gpt-oss-20b
//   ZIA_PASSCODE   optional secret; when set, the app asks for it once per device

export const IMAGE_TYPES = { "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp" };
export const IMAGE_NAME = /^[0-9a-f]{24}\.(jpg|png|webp)$/;
export const MAX_IMAGE = 1_900_000; // D1 rows top out at 2 MB; the app shrinks photos well below this
export const MODEL_DEFAULT = "openai/gpt-oss-20b";

export function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
}

export function authed(request, env) {
  const pass = env.ZIA_PASSCODE || "";
  if (!pass) return true;
  const got = request.headers.get("X-Zia-Key") || "";
  if (got.length !== pass.length) return false;
  let diff = 0;
  for (let i = 0; i < got.length; i++) diff |= got.charCodeAt(i) ^ pass.charCodeAt(i);
  return diff === 0;
}

let tablesReady = false;
export async function db(env) {
  if (!env.DB) throw Object.assign(new Error("D1 binding 'DB' is missing"), { status: 500 });
  if (!tablesReady) {
    await env.DB.batch([
      env.DB.prepare("CREATE TABLE IF NOT EXISTS store (k TEXT PRIMARY KEY, v TEXT NOT NULL)"),
      env.DB.prepare("CREATE TABLE IF NOT EXISTS images (name TEXT PRIMARY KEY, type TEXT NOT NULL, data BLOB NOT NULL, created INTEGER NOT NULL)")
    ]);
    tablesReady = true;
  }
  return env.DB;
}

export function randomHex(bytes) {
  return [...crypto.getRandomValues(new Uint8Array(bytes))].map(b => b.toString(16).padStart(2, "0")).join("");
}

const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
// Next 14 days as "Friday = 2026-10-23" lines, so the model never has to do date maths.
export function calendar(today) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(today || "");
  const base = m ? Date.UTC(+m[1], +m[2] - 1, +m[3]) : Date.now();
  const iso = d => d.toISOString().slice(0, 10);
  const rows = [];
  for (let n = 0; n < 15; n++) {
    const d = new Date(base + n * 864e5);
    const label = n === 0 ? "today" : n === 1 ? "tomorrow" : DAY_NAMES[d.getUTCDay()] + (n > 7 ? " next week" : "");
    rows.push(`${label} = ${iso(d)}`);
  }
  const d0 = new Date(base);
  return { today: iso(d0), weekday: DAY_NAMES[d0.getUTCDay()], cal: rows.join("\n") };
}

export const SYSTEM = `You are Zia, a voice-first personal agent for one person who is BOTH a college student and a startup founder.
You track what they HAVE to do and keep both lives balanced. You are not a tutor: don't explain study topics.
You may give brief, practical advice on what to do first.

The user speaks (speech-to-text, so expect typos and filler). You get today's calendar, their task list and the recent conversation.
Reply with ONLY a JSON object:
{"reply": "<what you say aloud: max 45 words, warm, natural, conversational, no markdown, no lists>",
 "actions": [ ... ]}

Action types:
 {"type":"add","text":"<short clean task title>","side":"student|founder","cat":"<category>","pri":1|2|3,"due":"YYYY-MM-DD or empty"}
 {"type":"done","id":"<id>"}       mark finished
 {"type":"undo","id":"<id>"}       mark pending again
 {"type":"delete","id":"<id>"}     remove
 {"type":"edit","id":"<id>", any of "text","side","cat","pri","due"}   change a task (e.g. move a deadline)

Categories: student -> Assignment, Exam, Project, Lab, Other. founder -> Product, Customers, Fundraising, Team, Other.
pri: 3 = urgent/important, 2 = normal, 1 = low.

Rules:
- The words come from speech recognition. Fix obvious mishearings (e.g. "full strike" -> "full stack", "big data analytic" -> "Big Data Analytics"),
  drop filler like "I have", "there is", "institute for", and keep task titles short and clean (2-6 words, Title Case).
- One sentence may contain several tasks: return one add action each.
- Resolve dates ONLY from the calendar given. Leave due empty if none was said.
- Only use ids from the task list. Never invent ids. Use the conversation to resolve "that", "it", "the last one".
- If a request is ambiguous, ask one short question and return no actions.
- For questions (what do I have / what's due / what first / how am I doing) answer from the list with no actions:
  overdue first, then the nearest deadlines; gently flag if student or founder work is being neglected.
- Never claim you changed something you did not put in actions. Don't read out ids or dates in YYYY-MM-DD form; say "Friday", "tomorrow".`;

export async function askGroq(env, said, items, today, history) {
  const { today: t, weekday, cal } = calendar(today);
  const pending = items.filter(i => !i.done), recentDone = items.filter(i => i.done).slice(-8);
  const lines = [...pending, ...recentDone].map(i =>
    `id=${i.id} | ${i.side}/${i.cat} | "${i.text}" | pri ${i.pri ?? 2} | due ${i.due || "none"} | ${i.done ? "DONE" : "pending"}`);
  const user = `Today is ${t} (${weekday}). Calendar (a bare weekday means its first occurrence):\n${cal}\n\n` +
    `Task list:\n${lines.join("\n") || "(empty)"}\n\nUser said: "${said}"`;
  const messages = [{ role: "system", content: SYSTEM }];
  for (const h of history.slice(-8)) {
    if (h && (h.role === "user" || h.role === "assistant") && typeof h.content === "string") messages.push({ role: h.role, content: h.content.slice(0, 500) });
  }
  messages.push({ role: "user", content: user });
  const r = await fetch("https://api.groq.com/openai/v1/chat/completions", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${env.GROQ_API_KEY}` },
    body: JSON.stringify({
      model: env.GROQ_MODEL || MODEL_DEFAULT, temperature: 0.3, max_tokens: 1400, reasoning_effort: "low",
      response_format: { type: "json_object" }, messages
    })
  });
  if (!r.ok) throw Object.assign(new Error(`Groq HTTP ${r.status}`), { status: 502 });
  const data = await r.json();
  const out = JSON.parse(data.choices[0].message.content);
  return { reply: String(out.reply || ""), actions: Array.isArray(out.actions) ? out.actions : [] };
}
