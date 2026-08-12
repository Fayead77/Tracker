# LearnFlow

A personal learning-progress tracker: Category → Subject → your own two custom levels (e.g. Milestone → Module, or Chapter → Topic) → checklist items with notes and resources. Includes a dashboard, streak/badge tracking, analytics, and a resources view.

There's no login/signup — the app opens straight in. It's meant for one person's use (you), whether you're running it locally on your Mac or visiting your own Render link.

## Data storage

- **Running locally** (`Start LearnFlow.command`): data is saved in a `database.db` SQLite file in this folder. Your Mac's disk is permanent, so this is safe as-is.
- **Deployed on Render**: Render's free tier disk is *not* permanent — it can be wiped whenever the server restarts, redeploys, or wakes up from sleeping. To keep your data safe there, connect a free, permanent Postgres database (Supabase or Neon both work) — see below.

## Setting up a free permanent database for Render

You only need to do this once. Pick **either** Supabase or Neon — both have a permanent free tier.

### Option A: Supabase

1. Go to https://supabase.com and sign up (free), then create a new project.
2. Once it's created, go to **Project Settings → Database**.
3. Under **Connection string**, choose the **URI** tab, and copy the connection string. It looks like:
   ```
   postgresql://postgres:[YOUR-PASSWORD]@db.xxxxxxxxxxxx.supabase.co:5432/postgres
   ```
   Replace `[YOUR-PASSWORD]` with the database password you set when creating the project. If you're on Supabase's pooled/IPv4 connection option, use the "Connection pooling" URI instead — either works.

### Option B: Neon

1. Go to https://neon.tech and sign up (free), then create a new project.
2. On the project dashboard, find the **Connection string** box and copy it. It looks like:
   ```
   postgresql://username:password@ep-xxxx-xxxx.region.aws.neon.tech/neondb?sslmode=require
   ```

### Connect it to Render

1. Open your service on Render → **Environment** (left sidebar).
2. Add a new environment variable:
   - **Key:** `DATABASE_URL`
   - **Value:** the connection string you copied above
3. Save — Render will automatically redeploy. On startup, the app detects `DATABASE_URL` and creates its tables in that Postgres database automatically (nothing else to run manually).
4. That's it. From now on, your data lives in Supabase/Neon and will survive Render restarts, redeploys, and sleep/wake cycles.

**Note:** if you had already been using the site on Render before this, that old data was in the ephemeral SQLite file and won't carry over automatically — you'll start fresh in the new database the first time it connects.

## If the site feels slow

A few things help, roughly in order of impact:

1. **Use the "pooled" connection string, not the direct one**, if your provider offers both:
   - Supabase: use the **Connection pooling** URI (port `6543`), not the direct one (port `5432`).
   - Neon: the connection string Neon gives you by default is already the pooled one.
   The app itself also now keeps a small pool of reused connections internally, so it isn't opening a brand-new connection to your database on every click — but starting from an already-pooled provider URL helps further.
2. **Pick the region closest to your Render service** when creating the Supabase/Neon project — every query has to travel over the internet between Render and your database, so a distant region adds noticeable delay to *everything*, not just bulk import.
3. **The very first request after the site has been idle for a while will always be a bit slower** — free-tier Postgres (especially Neon) suspends itself when nobody's using it, and briefly wakes back up on the next request. This is normal and unavoidable on a free tier.

## Deploying on Render

1. Push this code to GitHub.
2. On Render, set the **Start Command** to:
   ```
   gunicorn app:app --bind 0.0.0.0:$PORT
   ```
   (The included `Procfile` already specifies this — Render should pick it up automatically.)
3. Set the `DATABASE_URL` environment variable as described above so your data persists.

## Running locally (Mac)

Double-click **`Start LearnFlow.command`** in this folder. It sets everything up the first time, then starts the server and opens the app in your browser. Leave that window open while you use the app — closing it stops the server.

(If macOS blocks it the first time: right-click the file → Open, then confirm "Open" in the dialog. You only need to do this once.)

This always uses the local `database.db` file — it ignores `DATABASE_URL` entirely, since that's only meant for the Render deployment.

## Manual setup (alternative)

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5001 in your browser.

## Structure

- `app.py` — Flask app: routes, data model, progress/streak/badge logic
- `db_compat.py` — database layer: uses Postgres when `DATABASE_URL` is set (Render), otherwise the local SQLite file
- `schema.sql` — SQLite schema (local use)
- `schema_postgres.sql` — Postgres schema (Render + Supabase/Neon)
- `templates/index.html` — single-page app shell
- `static/css/style.css` — styling (responsive down to small phone widths)
- `static/js/script.js` — all frontend logic (view routing, API calls, rendering)
- `Procfile` — tells Render how to start the app in production

## Adding a subject

Give it a name, a category, and two labels for your own hierarchy (e.g. "Milestone"/"Module"). Then either bulk-paste a syllabus (unindented lines = top level, indented lines = items under it) or add items manually.
