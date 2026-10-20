# Zia

A voice-first agent for someone who is both a college student and a startup founder.
Tell Zia what you have; it tracks it on a node map, a calendar and a task list, and answers out loud.

## Run on your PC

1. Put your Groq key in a `.env` file next to `krefter_server.py`:
   ```
   GROQ_API_KEY=your-key
   ```
2. `python krefter_server.py`
3. Open http://localhost:8765

## Host on Cloudflare Pages (free)

The `functions/` folder is the online backend; `public/` is the app.

1. **Create the database:** Cloudflare dashboard → Storage & Databases → D1 → Create → name it `zia-db`.
2. **Create the site:** Workers & Pages → Create → **Pages** → Import an existing Git repository → `AgentZia`.
   - Framework preset: None
   - Build command: *(leave empty)*
   - Build output directory: `public`
3. **Connect the database and key:** in the Pages project → Settings:
   - Bindings → Add → D1 database → Variable name `DB` → `zia-db`
   - Variables and Secrets → Add → `GROQ_API_KEY` (type: Secret)
   - Optional: `ZIA_PASSCODE` (Secret) to require a passcode on each new device
   - Then Deployments → Retry deployment, so the new settings take effect.
4. **Use your domain:** Pages project → Custom domains → `zia.sprintevent.co.in`.
   In GoDaddy DNS add a **CNAME** record: Name `zia`, Value `<project>.pages.dev`.

Every push to `main` redeploys automatically.

Never commit `.env` or `.dev.vars`; they hold your Groq key.
