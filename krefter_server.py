"""Zia server: serves the app, stores your tasks, and talks to Groq so your key never reaches the browser.

Run:   python krefter_server.py
Open:  http://localhost:8765
Config (.env next to this file):
  GROQ_API_KEY=...        required for AI replies
  GROQ_MODEL=...          optional, default openai/gpt-oss-20b
  ZIA_PASSCODE=...        strongly recommended once the app is online
  HOST=0.0.0.0 / PORT=... optional, for hosting (default 127.0.0.1:8765)
No pip installs required.
"""
import hmac
import json
import os
import re
import secrets
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "krefter_store.json")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
UPLOADS = os.path.join(HERE, "uploads")
MAX_BODY = 20_000_000
MAX_IMAGE = 20_000_000
IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf"}  # photos and PDFs
IMAGE_NAME = re.compile(r"^[0-9a-f]{24}\.(jpg|png|webp|pdf)$")


def load_env():
    path = os.path.join(HERE, ".env")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()
KEY = os.environ.get("GROQ_API_KEY", "")
MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
PASSCODE = os.environ.get("ZIA_PASSCODE") or os.environ.get("KREFTER_PASSCODE", "")
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))
store_lock = threading.Lock()

SYSTEM = """You are Zia, a voice-first personal agent for one person who is BOTH a college student and a startup founder.
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
 {"type":"link","url":"https://...","id":"<task id or empty>"}   pin a web link on the board, attached to that task if one is named

Categories: student -> Assignment, Exam, Project, Lab, Other. founder -> Product, Customers, Fundraising, Team, Other.
pri: 3 = urgent/important, 2 = normal, 1 = low.

Rules:
- The words come from speech recognition. Fix obvious mishearings (e.g. "full strike" -> "full stack", "big data analytic" -> "Big Data Analytics"),
  drop filler like "I have", "there is", "institute for", and keep task titles short and clean (2-6 words, Title Case).
- One sentence may contain several tasks: return one add action each.
- If the user gives a web address, pin it with a link action (attach it to the task they mention, if any).
- Resolve dates ONLY from the calendar given. Leave due empty if none was said.
- Only use ids from the task list. Never invent ids. Use the conversation to resolve "that", "it", "the last one".
- If a request is ambiguous, ask one short question and return no actions.
- For questions (what do I have / what's due / what first / how am I doing) answer from the list with no actions:
  overdue first, then the nearest deadlines; gently flag if student or founder work is being neglected.
- Never claim you changed something you did not put in actions. Don't read out ids or dates in YYYY-MM-DD form; say "Friday", "tomorrow"."""


# Separate boards picked by ?u= (the page sends it from /hari, /keerthi); same list as lib/zia.js.
# "single" boards have one parent node ("You") instead of the Student and Founder hubs.
PROFILES = {"": {"name": "", "single": False}, "hari": {"name": "Hari Haran", "single": True}, "keerthi": {"name": "Keerthilakshmi", "single": True}}
SINGLE_CATS = ["Exam", "Assignment", "Project", "Lab", "Work", "Personal", "Other"]


def profile_of(raw_path):
    query = urllib.parse.parse_qs(raw_path.split("?", 1)[1] if "?" in raw_path else "")
    u = (query.get("u") or [""])[0].lower()
    return u if u in PROFILES else None


def system_for(u):
    p = PROFILES.get(u) or PROFILES[""]
    if not p["single"]:
        return SYSTEM
    s = SYSTEM.replace(
        "for one person who is BOTH a college student and a startup founder.\nYou track what they HAVE to do and keep both lives balanced.",
        f"for {p['name']}. You track what they HAVE to do.")
    s = s.replace(',"side":"student|founder"', "").replace(' any of "text","side","cat"', ' any of "text","cat"')
    s = re.sub(r"Categories: student -> .*\n", "Categories: " + ", ".join(SINGLE_CATS) + ".\n", s)
    return s.replace("; gently flag if student or founder work is being neglected", "")


def calendar(today):
    """Next 14 days as 'Friday = 2026-10-23' lines, so the model never has to do date math."""
    try:
        d0 = date.fromisoformat(today)
    except ValueError:
        d0 = date.today()
    rows = []
    for n in range(0, 15):
        d = d0 + timedelta(days=n)
        label = "today" if n == 0 else "tomorrow" if n == 1 else d.strftime("%A") + (" next week" if n > 7 else "")
        rows.append(f"{label} = {d.isoformat()}")
    return d0, "\n".join(rows)


def ask_groq(said, items, today, history, u=""):
    d0, cal = calendar(today)
    pending = [i for i in items if not i.get("done")]
    recent_done = [i for i in items if i.get("done")][-8:]
    lines = [
        f'id={i.get("id")} | {"" if PROFILES.get(u, {}).get("single") else str(i.get("side")) + "/"}{i.get("cat")} | "{i.get("text")}" | pri {i.get("pri", 2)} | '
        f'due {i.get("due") or "none"} | {"DONE" if i.get("done") else "pending"}'
        for i in pending + recent_done
    ]
    user = (
        f"Today is {d0.isoformat()} ({d0.strftime('%A')}). Calendar (a bare weekday means its first occurrence):\n{cal}\n\n"
        f"Task list:\n" + ("\n".join(lines) or "(empty)") + f'\n\nUser said: "{said}"'
    )
    messages = [{"role": "system", "content": system_for(u)}]
    for h in history[-8:]:
        if isinstance(h, dict) and h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str):
            messages.append({"role": h["role"], "content": h["content"][:500]})
    messages.append({"role": "user", "content": user})
    body = {
        "model": MODEL,
        "temperature": 0.3,
        "max_tokens": 1400,
        "reasoning_effort": "low",
        "response_format": {"type": "json_object"},
        "messages": messages,
    }
    req = urllib.request.Request(
        GROQ_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}", "User-Agent": "zia/2.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    out = json.loads(data["choices"][0]["message"]["content"])
    return {"reply": str(out.get("reply", "")), "actions": out.get("actions") or []}


def parse_meta(html, base):
    """Title, preview image and description of a web page, for link cards on the board."""
    from html import unescape

    def meta(name):
        tag = re.search(r"<meta[^>]+(?:property|name)=[\"']" + re.escape(name) + r"[\"'][^>]*>", html, re.I)
        m = re.search(r"content=[\"']([^\"']*)[\"']", tag.group(0), re.I) if tag else None
        return unescape(m.group(1)).strip() if m else ""

    t = re.search(r"<title[^>]*>([^<]*)</title>", html, re.I)
    title = meta("og:title") or meta("twitter:title") or (unescape(t.group(1)).strip() if t else "")
    image = meta("og:image") or meta("twitter:image")
    image = urllib.parse.urljoin(base, image) if image else ""
    if not image.startswith("https:"):
        image = ""  # http images would be blocked on an https page
    return {"title": title[:140], "image": image, "description": (meta("og:description") or meta("description"))[:200]}


def link_info(url):
    if not re.match(r"^https?://", url or ""):
        return {"title": "", "image": "", "description": ""}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; ZiaLinkPreview/1.0)", "Accept": "text/html,*/*"})
        with urllib.request.urlopen(req, timeout=8) as r:
            ctype = r.headers.get("Content-Type", "")
            if "html" not in ctype:
                return {"title": "", "image": url if ctype.startswith("image/") and url.startswith("https:") else "", "description": ""}
            html = r.read(400_000).decode(r.headers.get_content_charset() or "utf-8", "replace")
            return parse_meta(html, r.geturl())
    except Exception:
        return {"title": "", "image": "", "description": ""}


def store_path(u):
    return STORE if not u else os.path.join(HERE, f"krefter_store.{u}.json")


def read_store(u=""):
    with store_lock:
        if not os.path.exists(store_path(u)):
            return {"items": [], "chat": [], "images": []}
        with open(store_path(u), "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("images", [])
        return data


def write_store(data, u=""):
    with store_lock:
        tmp = store_path(u) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, store_path(u))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_json(self, code, obj):
        raw = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def authed(self):
        if not PASSCODE:
            return True
        got = self.headers.get("X-Zia-Key", "")
        return hmac.compare_digest(got.encode("utf-8"), PASSCODE.encode("utf-8"))

    def read_json(self):
        n = int(self.headers.get("Content-Length", 0))
        if n > MAX_BODY:
            raise ValueError("too large")
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html", "/krefter.html") or path.strip("/").lower() in PROFILES:
            with open(os.path.join(HERE, "public", "index.html"), "rb") as f:
                raw = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(raw)
        elif path.startswith("/uploads/"):
            # file names are 24 random hex chars, so they can't be guessed or used to escape the folder
            name = path[len("/uploads/"):]
            full = os.path.join(UPLOADS, name)
            if not IMAGE_NAME.match(name) or not os.path.exists(full):
                return self.send_json(404, {"error": "not found"})
            with open(full, "rb") as f:
                raw = f.read()
            ext = name.rsplit(".", 1)[1]
            self.send_response(200)
            self.send_header("Content-Type", {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp", "pdf": "application/pdf"}[ext])
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "private, max-age=31536000, immutable")
            self.end_headers()
            self.wfile.write(raw)
        elif path == "/api/linkinfo":
            if not self.authed():
                return self.send_json(401, {"error": "locked"})
            query = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            self.send_json(200, link_info((query.get("url") or [""])[0]))
        elif path == "/api/health":
            self.send_json(200, {"ai": bool(KEY), "model": MODEL, "locked": bool(PASSCODE)})
        elif path == "/api/items":
            if not self.authed():
                return self.send_json(401, {"error": "locked"})
            u = profile_of(self.path)
            if u is None:
                return self.send_json(404, {"error": "unknown profile"})
            self.send_json(200, read_store(u))
        else:
            self.send_json(404, {"error": "not found"})

    def do_PUT(self):
        u = profile_of(self.path)
        if self.path.split("?", 1)[0] != "/api/items" or u is None:
            return self.send_json(404, {"error": "not found"})
        if not self.authed():
            return self.send_json(401, {"error": "locked"})
        try:
            req = self.read_json()
            items = [i for i in req.get("items", []) if isinstance(i, dict)][:2000]
            chat = [m for m in req.get("chat", []) if isinstance(m, dict)][-100:]
            images = [m for m in req.get("images", []) if isinstance(m, dict)][:500]
            write_store({"items": items, "chat": chat, "images": images}, u)
            self.send_json(200, {"ok": True})
        except Exception as e:
            self.send_json(400, {"error": type(e).__name__})

    def do_DELETE(self):
        name = self.path[len("/api/upload/"):] if self.path.startswith("/api/upload/") else ""
        if not IMAGE_NAME.match(name):
            return self.send_json(404, {"error": "not found"})
        if not self.authed():
            return self.send_json(401, {"error": "locked"})
        full = os.path.join(UPLOADS, name)
        if os.path.exists(full):
            os.remove(full)
        self.send_json(200, {"ok": True})

    def upload(self):
        if not self.authed():
            return self.send_json(401, {"error": "locked"})
        ctype = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        n = int(self.headers.get("Content-Length", 0))
        if ctype not in IMAGE_TYPES or not 0 < n <= MAX_IMAGE:
            return self.send_json(400, {"error": "send a photo (JPEG, PNG, WebP) or a PDF under 20 MB"})
        os.makedirs(UPLOADS, exist_ok=True)
        name = secrets.token_hex(12) + IMAGE_TYPES[ctype]
        with open(os.path.join(UPLOADS, name), "wb") as f:
            f.write(self.rfile.read(n))
        self.send_json(200, {"url": "/uploads/" + name})

    def do_POST(self):
        if self.path == "/api/upload":
            return self.upload()
        u = profile_of(self.path)
        if self.path.split("?", 1)[0] != "/api/chat" or u is None:
            return self.send_json(404, {"error": "not found"})
        if not self.authed():
            return self.send_json(401, {"error": "locked"})
        if not KEY:
            return self.send_json(503, {"error": "GROQ_API_KEY missing in .env"})
        try:
            req = self.read_json()
            said = str(req.get("said", ""))[:600]
            items = [i for i in req.get("items", []) if isinstance(i, dict)][:300]
            history = req.get("history", []) if isinstance(req.get("history"), list) else []
            self.send_json(200, ask_groq(said, items, str(req.get("today", "")), history, u))
        except urllib.error.HTTPError as e:
            self.send_json(502, {"error": f"Groq HTTP {e.code}"})
        except Exception as e:
            self.send_json(500, {"error": type(e).__name__})


if __name__ == "__main__":
    print(f"Zia running at http://localhost:{PORT}")
    print(f"  AI: {'on, ' + MODEL if KEY else 'OFF - add GROQ_API_KEY to .env'}")
    print(f"  Passcode: {'on' if PASSCODE else 'off (set ZIA_PASSCODE in .env before putting this online)'}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
