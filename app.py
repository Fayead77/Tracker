import sqlite3
import os
import secrets
from datetime import datetime, timedelta
from flask import Flask, g, jsonify, request, render_template
from werkzeug.security import generate_password_hash

import db_compat

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "database.db")
SCHEMA_PATH = os.path.join(APP_DIR, "schema.sql")

app = Flask(__name__)


# Cache-busting: appends each static file's last-modified time as a query
# string (?v=...) so phones/browsers never keep serving a stale, cached
# CSS/JS file after a new deploy — this is a common reason "fixed" changes
# don't visibly show up on a phone until the cache is manually cleared.
@app.context_processor
def inject_asset_version():
    def asset_url(filename):
        path = os.path.join(app.static_folder, filename)
        try:
            v = int(os.path.getmtime(path))
        except OSError:
            v = 0
        from flask import url_for
        return f"{url_for('static', filename=filename)}?v={v}"
    return dict(asset_url=asset_url)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = db_compat.connect()
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        with open(SCHEMA_PATH, "r") as f:
            conn.executescript(f.read())


def migrate_db():
    """Add any new columns/tables to an existing database without touching its data."""
    with sqlite3.connect(DB_PATH) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(subjects)").fetchall()]
        if "pinned" not in cols:
            conn.execute("ALTER TABLE subjects ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
            conn.commit()
        if "sort_order" not in cols:
            conn.execute("ALTER TABLE subjects ADD COLUMN sort_order INTEGER DEFAULT 0")
            conn.commit()    

        resource_cols = [r[1] for r in conn.execute("PRAGMA table_info(resources)").fetchall()]
        if "subject_id" not in resource_cols:
            conn.executescript(
                """
                CREATE TABLE resources_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject_id INTEGER NOT NULL,
                    level2_id INTEGER,
                    type TEXT NOT NULL,
                    value TEXT NOT NULL
                );
                INSERT INTO resources_new (id, subject_id, level2_id, type, value)
                SELECT r.id,
                       (SELECT l1.subject_id FROM level2 l2 JOIN level1 l1 ON l2.level1_id = l1.id WHERE l2.id = r.level2_id),
                       r.level2_id, r.type, r.value
                FROM resources r;
                DROP TABLE resources;
                ALTER TABLE resources_new RENAME TO resources;
                """
            )
            conn.commit()

        level2_cols = [r[1] for r in conn.execute("PRAGMA table_info(level2)").fetchall()]
        if "flagged" not in level2_cols:
            conn.execute("ALTER TABLE level2 ADD COLUMN flagged INTEGER NOT NULL DEFAULT 0")
            conn.commit()

        # --- Accounts migration: add users table + user_id columns, and
        # assign any pre-existing (pre-accounts) data to a fallback account
        # so nothing already stored is lost. ---
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if "users" not in tables:
            conn.execute(
                """CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now'))
                )"""
            )
            conn.commit()

        cat_cols = [r[1] for r in conn.execute("PRAGMA table_info(categories)").fetchall()]
        subj_cols = [r[1] for r in conn.execute("PRAGMA table_info(subjects)").fetchall()]
        activity_cols = [r[1] for r in conn.execute("PRAGMA table_info(activity_log)").fetchall()]
        badge_cols = [r[1] for r in conn.execute("PRAGMA table_info(badges)").fetchall()]
        needs_fallback_user = (
            "user_id" not in cat_cols or "user_id" not in subj_cols
        )

        fallback_user_id = None
        if needs_fallback_user:
            existing_fallback = conn.execute(
                "SELECT id FROM users WHERE username = 'legacy_data'"
            ).fetchone()
            if existing_fallback:
                fallback_user_id = existing_fallback[0]
            else:
                cur = conn.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    ("legacy_data", generate_password_hash("changeme123")),
                )
                fallback_user_id = cur.lastrowid
            conn.commit()

        if "user_id" not in cat_cols:
            conn.execute("ALTER TABLE categories ADD COLUMN user_id INTEGER")
            conn.execute("UPDATE categories SET user_id = ? WHERE user_id IS NULL", (fallback_user_id,))
            conn.commit()

        if "user_id" not in subj_cols:
            conn.execute("ALTER TABLE subjects ADD COLUMN user_id INTEGER")
            conn.execute("UPDATE subjects SET user_id = ? WHERE user_id IS NULL", (fallback_user_id,))
            conn.commit()

        if "user_id" not in activity_cols:
            conn.execute("ALTER TABLE activity_log ADD COLUMN user_id INTEGER")
            conn.execute("UPDATE activity_log SET user_id = ? WHERE user_id IS NULL", (fallback_user_id,))
            conn.commit()

        if "user_id" not in badge_cols:
            conn.execute("ALTER TABLE badges ADD COLUMN user_id INTEGER")
            conn.execute("UPDATE badges SET user_id = ? WHERE user_id IS NULL", (fallback_user_id,))
            conn.commit()

        # --- Accounts removal: the app no longer has a login/signup screen —
        # everything now lives under one single built-in account. Any data
        # that was previously split across different user accounts (e.g. on
        # a machine where real accounts were created before) is merged back
        # together under that one account, so nothing already saved goes
        # missing after this update. ---
        default_row = conn.execute(
            "SELECT id FROM users WHERE username = ?", (DEFAULT_USERNAME,)
        ).fetchone()
        if default_row:
            default_user_id = default_row[0]
        else:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (DEFAULT_USERNAME, generate_password_hash(secrets.token_hex(16))),
            )
            default_user_id = cur.lastrowid
            conn.commit()

        for table in ("categories", "subjects", "activity_log", "badges"):
            conn.execute(
                f"UPDATE {table} SET user_id = ? WHERE user_id IS NULL OR user_id != ?",
                (default_user_id, default_user_id),
            )
        conn.commit()


def row_to_dict(row):
    return dict(row) if row else None


def today_str():
    return datetime.utcnow().strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# No login/signup — the app opens straight in and everything runs under one
# fixed built-in account, the same way it worked before accounts existed.
# The users table + user_id columns stay in the schema (harmless, and it
# keeps every other query below unchanged), they're just never exposed
# through any login/signup screen anymore.
# ---------------------------------------------------------------------------
DEFAULT_USERNAME = "default"


def ensure_default_user(conn):
    row = conn.execute("SELECT id FROM users WHERE username = ?", (DEFAULT_USERNAME,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        (DEFAULT_USERNAME, generate_password_hash(secrets.token_hex(16))),
    )
    conn.commit()
    return cur.lastrowid


def current_user_id():
    if "user_id" not in g:
        db = get_db()
        g.user_id = ensure_default_user(db)
    return g.user_id


# ---------------------------------------------------------------------------
# Progress % utility — the single source of truth for progress calculations.
# Works at level1, subject, and overall (all-subjects) granularity.
# ---------------------------------------------------------------------------
def calc_progress(completed, total):
    if total == 0:
        return 0
    return round((completed / total) * 100)


def level1_progress(db, level1_id):
    row = db.execute(
        "SELECT COUNT(*) AS total, SUM(done) AS completed FROM level2 WHERE level1_id = ?",
        (level1_id,),
    ).fetchone()
    total = row["total"] or 0
    completed = row["completed"] or 0
    return {"completed": completed, "total": total, "percent": calc_progress(completed, total)}


def subject_progress(db, subject_id):
    row = db.execute(
        """SELECT COUNT(l2.id) AS total, SUM(l2.done) AS completed
           FROM level2 l2
           JOIN level1 l1 ON l2.level1_id = l1.id
           WHERE l1.subject_id = ?""",
        (subject_id,),
    ).fetchone()
    total = row["total"] or 0
    completed = row["completed"] or 0
    return {"completed": completed, "total": total, "percent": calc_progress(completed, total)}


def overall_progress(db, uid):
    row = db.execute(
        """SELECT COUNT(l2.id) AS total, SUM(l2.done) AS completed
           FROM level2 l2 JOIN level1 l1 ON l2.level1_id = l1.id
           JOIN subjects s ON l1.subject_id = s.id WHERE s.user_id = ?""",
        (uid,),
    ).fetchone()
    total = row["total"] or 0
    completed = row["completed"] or 0
    return {"completed": completed, "total": total, "percent": calc_progress(completed, total)}


def subject_last_studied(db, subject_id):
    row = db.execute(
        "SELECT MAX(date) AS last_date FROM activity_log WHERE subject_id = ?", (subject_id,)
    ).fetchone()
    return row["last_date"]


def owns_subject(db, subject_id, uid):
    return db.execute(
        "SELECT id FROM subjects WHERE id = ? AND user_id = ?", (subject_id, uid)
    ).fetchone() is not None


def owned_level1_subject_id(db, level1_id, uid):
    """Return the subject_id for a level1 row if it belongs to uid, else None."""
    row = db.execute(
        "SELECT subject_id FROM level1 WHERE id = ?", (level1_id,)
    ).fetchone()
    if not row or not owns_subject(db, row["subject_id"], uid):
        return None
    return row["subject_id"]


def owned_level2_ids(db, level2_id, uid):
    """Return (level1_id, subject_id) for a level2 row if it belongs to uid, else (None, None)."""
    row = db.execute(
        """SELECT l1.id AS level1_id, l1.subject_id AS subject_id
           FROM level2 l2 JOIN level1 l1 ON l2.level1_id = l1.id WHERE l2.id = ?""",
        (level2_id,),
    ).fetchone()
    if not row or not owns_subject(db, row["subject_id"], uid):
        return None, None
    return row["level1_id"], row["subject_id"]


# ---------------------------------------------------------------------------
# Badge helper — called whenever a level2 item is toggled done.
# ---------------------------------------------------------------------------
def check_and_award_badge(db, level1_id, subject_id, uid):
    prog = level1_progress(db, level1_id)
    if prog["total"] > 0 and prog["completed"] == prog["total"]:
        existing = db.execute(
            "SELECT id FROM badges WHERE level1_id = ?", (level1_id,)
        ).fetchone()
        if not existing:
            db.execute(
                "INSERT INTO badges (user_id, subject_id, level1_id, earned_date) VALUES (?, ?, ?, ?)",
                (uid, subject_id, level1_id, today_str()),
            )
            db.commit()
            return True
    return False


# ---------------------------------------------------------------------------
# Page route
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Category API
# ---------------------------------------------------------------------------
@app.route("/api/categories", methods=["GET"])
def get_categories():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM categories WHERE user_id = ? ORDER BY name", (current_user_id(),)
    ).fetchall()
    return jsonify([row_to_dict(r) for r in rows])


@app.route("/api/categories", methods=["POST"])
def create_category():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Category name is required"}), 400
    db = get_db()
    uid = current_user_id()
    try:
        cur = db.execute("INSERT INTO categories (user_id, name) VALUES (?, ?)", (uid, name))
        db.commit()
    except db_compat.IntegrityErrors:
        db.rollback()
        existing = db.execute(
            "SELECT * FROM categories WHERE user_id = ? AND name = ?", (uid, name)
        ).fetchone()
        return jsonify(row_to_dict(existing)), 200
    new_row = db.execute("SELECT * FROM categories WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(row_to_dict(new_row)), 201


# ---------------------------------------------------------------------------
# Subject API
# ---------------------------------------------------------------------------
@app.route("/api/subjects", methods=["GET"])
def get_subjects():
    db = get_db()
    rows = db.execute(
       ORDER BY s.pinned DESC, s.sort_order, s.created_at DESC"""
           FROM subjects s JOIN categories c ON s.category_id = c.id
           WHERE s.user_id = ?
           ORDER BY s.pinned DESC, s.created_at DESC""",
        (current_user_id(),),
    ).fetchall()
    result = []
    for r in rows:
        d = row_to_dict(r)
        d["progress"] = subject_progress(db, r["id"])
        d["last_studied"] = subject_last_studied(db, r["id"])
        result.append(d)
    return jsonify(result)


@app.route("/api/subjects/<int:subject_id>/pin", methods=["POST"])
def toggle_pin(subject_id):
    db = get_db()
    row = db.execute(
        "SELECT pinned FROM subjects WHERE id = ? AND user_id = ?", (subject_id, current_user_id())
    ).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404
    new_val = 0 if row["pinned"] else 1
    db.execute("UPDATE subjects SET pinned = ? WHERE id = ?", (new_val, subject_id))
    db.commit()
    return jsonify({"pinned": bool(new_val)})

@app.route("/api/subjects", methods=["POST"])
def create_subject():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    category_id = data.get("category_id")
    level1_label = (data.get("level1_label") or "Milestone").strip()
    level2_label = (data.get("level2_label") or "Module").strip()
    if not name or not category_id:
        return jsonify({"error": "name and category_id are required"}), 400
    db = get_db()
    uid = current_user_id()
    owned_cat = db.execute(
        "SELECT id FROM categories WHERE id = ? AND user_id = ?", (category_id, uid)
    ).fetchone()
    if not owned_cat:
        return jsonify({"error": "Category not found"}), 404
    cur = db.execute(
        "INSERT INTO subjects (user_id, name, category_id, level1_label, level2_label) VALUES (?, ?, ?, ?, ?)",
        (uid, name, category_id, level1_label, level2_label),
    )
    db.commit()
    new_row = db.execute(
        """SELECT s.*, c.name AS category_name FROM subjects s
           JOIN categories c ON s.category_id = c.id WHERE s.id = ?""",
        (cur.lastrowid,),
    ).fetchone()
    d = row_to_dict(new_row)
    d["progress"] = subject_progress(db, cur.lastrowid)
    return jsonify(d), 201


@app.route("/api/subjects/<int:subject_id>", methods=["GET"])
def get_subject_detail(subject_id):
    db = get_db()
    subject_row = db.execute(
        """SELECT s.*, c.name AS category_name FROM subjects s
           JOIN categories c ON s.category_id = c.id WHERE s.id = ? AND s.user_id = ?""",
        (subject_id, current_user_id()),
    ).fetchone()
    if not subject_row:
        return jsonify({"error": "Subject not found"}), 404

    subject = row_to_dict(subject_row)
    subject["progress"] = subject_progress(db, subject_id)

    level1_rows = db.execute(
        "SELECT * FROM level1 WHERE subject_id = ? ORDER BY sort_order, id",
        (subject_id,),
    ).fetchall()

    level1_list = []
    for l1 in level1_rows:
        l1_dict = row_to_dict(l1)
        l1_dict["progress"] = level1_progress(db, l1["id"])
        level2_rows = db.execute(
            "SELECT * FROM level2 WHERE level1_id = ? ORDER BY sort_order, id",
            (l1["id"],),
        ).fetchall()
        level2_list = []
        for l2 in level2_rows:
            l2_dict = row_to_dict(l2)
            res_rows = db.execute(
                "SELECT * FROM resources WHERE level2_id = ?", (l2["id"],)
            ).fetchall()
            l2_dict["resources"] = [row_to_dict(r) for r in res_rows]
            level2_list.append(l2_dict)
        l1_dict["level2_items"] = level2_list
        level1_list.append(l1_dict)

    subject["level1_items"] = level1_list
    return jsonify(subject)


@app.route("/api/subjects/<int:subject_id>", methods=["DELETE"])
def delete_subject(subject_id):
    db = get_db()
    db.execute("DELETE FROM subjects WHERE id = ? AND user_id = ?", (subject_id, current_user_id()))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/subjects/<int:subject_id>", methods=["PUT"])
def update_subject(subject_id):
    data = request.get_json(force=True)
    db = get_db()
    owned = db.execute(
        "SELECT id FROM subjects WHERE id = ? AND user_id = ?", (subject_id, current_user_id())
    ).fetchone()
    if not owned:
        return jsonify({"error": "Subject not found"}), 404
    fields = []
    values = []
    if "name" in data and data["name"].strip():
        fields.append("name = ?")
        values.append(data["name"].strip())
    if "level1_label" in data and data["level1_label"].strip():
        fields.append("level1_label = ?")
        values.append(data["level1_label"].strip())
    if "level2_label" in data and data["level2_label"].strip():
        fields.append("level2_label = ?")
        values.append(data["level2_label"].strip())
    if fields:
        values.append(subject_id)
        db.execute(f"UPDATE subjects SET {', '.join(fields)} WHERE id = ?", values)
        db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Bulk import
# ---------------------------------------------------------------------------
def parse_bulk_text(text):
    """
    Indentation is relative, not absolute — the least-indented lines
    in the pasted text become Level1, anything indented more than that
    becomes Level2 under the current Level1. This way it still works
    even if every line in a paste carries the same incidental leading
    whitespace (common when copying from PDFs/docs).
    """
    lines = [l for l in text.split("\n") if l.strip()]
    if not lines:
        return []

    def leading_ws(line):
        return len(line) - len(line.lstrip(" \t"))

    base_indent = min(leading_ws(l) for l in lines)

    structure = []
    current = None
    for raw_line in lines:
        indent = leading_ws(raw_line)
        name = raw_line.strip()
        if indent <= base_indent:
            current = {"name": name, "level2_items": []}
            structure.append(current)
        else:
            if current is None:
                current = {"name": name, "level2_items": []}
                structure.append(current)
            else:
                current["level2_items"].append(name)
    return structure


@app.route("/api/subjects/<int:subject_id>/bulk_preview", methods=["POST"])
def bulk_preview(subject_id):
    if not owns_subject(get_db(), subject_id, current_user_id()):
        return jsonify({"error": "Subject not found"}), 404
    data = request.get_json(force=True)
    text = data.get("text", "")
    parsed = parse_bulk_text(text)
    return jsonify({"parsed": parsed})


@app.route("/api/subjects/<int:subject_id>/bulk_import", methods=["POST"])
def bulk_import(subject_id):
    db = get_db()
    if not owns_subject(db, subject_id, current_user_id()):
        return jsonify({"error": "Subject not found"}), 404
    data = request.get_json(force=True)
    text = data.get("text", "")
    parsed = parse_bulk_text(text)

    max_order_row = db.execute(
        "SELECT MAX(sort_order) AS m FROM level1 WHERE subject_id = ?", (subject_id,)
    ).fetchone()
    order = (max_order_row["m"] or 0) + 1

    # Insert every milestone/level1 row in a single round-trip, then every
    # module/level2 row in a single round-trip, instead of one query per
    # item — this is what made a big syllabus paste slow to import over a
    # remote database.
    l1_rows = [(subject_id, item["name"], order + i) for i, item in enumerate(parsed)]
    l1_ids = db_compat.insert_many(db, "level1", ("subject_id", "name", "sort_order"), l1_rows)

    l2_rows = []
    for l1_id, item in zip(l1_ids, parsed):
        for i, l2_name in enumerate(item["level2_items"]):
            l2_rows.append((l1_id, l2_name, i))
    if l2_rows:
        db_compat.insert_many(db, "level2", ("level1_id", "name", "sort_order"), l2_rows)

    db.commit()
    return jsonify({"ok": True, "level1_count": len(parsed)})


# ---------------------------------------------------------------------------
# Level1 API
# ---------------------------------------------------------------------------
@app.route("/api/level1", methods=["POST"])
def create_level1():
    data = request.get_json(force=True)
    subject_id = data.get("subject_id")
    name = (data.get("name") or "").strip()
    if not subject_id or not name:
        return jsonify({"error": "subject_id and name are required"}), 400
    db = get_db()
    if not owns_subject(db, subject_id, current_user_id()):
        return jsonify({"error": "Subject not found"}), 404
    max_order_row = db.execute(
        "SELECT MAX(sort_order) AS m FROM level1 WHERE subject_id = ?", (subject_id,)
    ).fetchone()
    order = (max_order_row["m"] or 0) + 1
    cur = db.execute(
        "INSERT INTO level1 (subject_id, name, sort_order) VALUES (?, ?, ?)",
        (subject_id, name, order),
    )
    db.commit()
    new_row = db.execute("SELECT * FROM level1 WHERE id = ?", (cur.lastrowid,)).fetchone()
    d = row_to_dict(new_row)
    d["progress"] = {"completed": 0, "total": 0, "percent": 0}
    d["level2_items"] = []
    return jsonify(d), 201


@app.route("/api/level1/<int:level1_id>", methods=["PUT"])
def update_level1(level1_id):
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    db = get_db()
    if not owned_level1_subject_id(db, level1_id, current_user_id()):
        return jsonify({"error": "Not found"}), 404
    if name:
        db.execute("UPDATE level1 SET name = ? WHERE id = ?", (name, level1_id))
        db.commit()
    return jsonify({"ok": True})


@app.route("/api/level1/<int:level1_id>", methods=["DELETE"])
def delete_level1(level1_id):
    db = get_db()
    if not owned_level1_subject_id(db, level1_id, current_user_id()):
        return jsonify({"error": "Not found"}), 404
    db.execute("DELETE FROM level1 WHERE id = ?", (level1_id,))
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Level2 API
# ---------------------------------------------------------------------------
@app.route("/api/level2", methods=["POST"])
def create_level2():
    data = request.get_json(force=True)
    level1_id = data.get("level1_id")
    name = (data.get("name") or "").strip()
    if not level1_id or not name:
        return jsonify({"error": "level1_id and name are required"}), 400
    db = get_db()
    if not owned_level1_subject_id(db, level1_id, current_user_id()):
        return jsonify({"error": "Not found"}), 404
    max_order_row = db.execute(
        "SELECT MAX(sort_order) AS m FROM level2 WHERE level1_id = ?", (level1_id,)
    ).fetchone()
    order = (max_order_row["m"] or 0) + 1
    cur = db.execute(
        "INSERT INTO level2 (level1_id, name, sort_order) VALUES (?, ?, ?)",
        (level1_id, name, order),
    )
    db.commit()
    new_row = db.execute("SELECT * FROM level2 WHERE id = ?", (cur.lastrowid,)).fetchone()
    d = row_to_dict(new_row)
    d["resources"] = []
    return jsonify(d), 201


@app.route("/api/level2/<int:level2_id>", methods=["PUT"])
def update_level2(level2_id):
    data = request.get_json(force=True)
    db = get_db()
    l1_id, subj_id = owned_level2_ids(db, level2_id, current_user_id())
    if not subj_id:
        return jsonify({"error": "Not found"}), 404
    fields = []
    values = []
    if "name" in data:
        fields.append("name = ?")
        values.append(data["name"].strip())
    if "notes" in data:
        fields.append("notes = ?")
        values.append(data["notes"])
    if fields:
        values.append(level2_id)
        db.execute(f"UPDATE level2 SET {', '.join(fields)} WHERE id = ?", values)
        db.commit()
    return jsonify({"ok": True})


@app.route("/api/level2/<int:level2_id>", methods=["DELETE"])
def delete_level2(level2_id):
    db = get_db()
    l1_id, subj_id = owned_level2_ids(db, level2_id, current_user_id())
    if not subj_id:
        return jsonify({"error": "Not found"}), 404
    db.execute("DELETE FROM level2 WHERE id = ?", (level2_id,))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/level2/<int:level2_id>/toggle", methods=["POST"])
def toggle_level2(level2_id):
    db = get_db()
    uid = current_user_id()
    row = db.execute(
        """SELECT l2.*, l1.subject_id AS subject_id FROM level2 l2
           JOIN level1 l1 ON l2.level1_id = l1.id WHERE l2.id = ?""",
        (level2_id,),
    ).fetchone()
    if not row or not owns_subject(db, row["subject_id"], uid):
        return jsonify({"error": "Not found"}), 404

    new_done = 0 if row["done"] else 1
    completed_at = today_str() if new_done else None
    db.execute(
        "UPDATE level2 SET done = ?, completed_at = ? WHERE id = ?",
        (new_done, completed_at, level2_id),
    )

    badge_earned = False
    if new_done:
        db.execute(
            "INSERT INTO activity_log (user_id, date, level2_id, subject_id) VALUES (?, ?, ?, ?)",
            (uid, today_str(), level2_id, row["subject_id"]),
        )
        db.commit()
        badge_earned = check_and_award_badge(db, row["level1_id"], row["subject_id"], uid)
    else:
        db.execute(
            "DELETE FROM activity_log WHERE level2_id = ? AND date = ?",
            (level2_id, today_str()),
        )
        db.commit()

    return jsonify(
        {
            "done": bool(new_done),
            "level1_progress": level1_progress(db, row["level1_id"]),
            "subject_progress": subject_progress(db, row["subject_id"]),
            "badge_earned": badge_earned,
        }
    )


@app.route("/api/level2/<int:level2_id>/flag", methods=["POST"])
def toggle_flag(level2_id):
    db = get_db()
    l1_id, subj_id = owned_level2_ids(db, level2_id, current_user_id())
    if not subj_id:
        return jsonify({"error": "Not found"}), 404
    row = db.execute("SELECT flagged FROM level2 WHERE id = ?", (level2_id,)).fetchone()
    new_val = 0 if row["flagged"] else 1
    db.execute("UPDATE level2 SET flagged = ? WHERE id = ?", (new_val, level2_id))
    db.commit()
    return jsonify({"flagged": bool(new_val)})


@app.route("/api/level2/<int:level2_id>/resources", methods=["POST"])
def add_resource(level2_id):
    data = request.get_json(force=True)
    r_type = (data.get("type") or "link").strip()
    value = (data.get("value") or "").strip()
    if not value:
        return jsonify({"error": "value is required"}), 400
    db = get_db()
    l1_id, subj_id = owned_level2_ids(db, level2_id, current_user_id())
    if not subj_id:
        return jsonify({"error": "Item not found"}), 404
    cur = db.execute(
        "INSERT INTO resources (subject_id, level2_id, type, value) VALUES (?, ?, ?, ?)",
        (subj_id, level2_id, r_type, value),
    )
    db.commit()
    return jsonify({"id": cur.lastrowid, "type": r_type, "value": value}), 201


@app.route("/api/subjects/<int:subject_id>/resources", methods=["POST"])
def add_subject_resource(subject_id):
    """Add a resource directly to a subject, not tied to a specific item."""
    data = request.get_json(force=True)
    r_type = (data.get("type") or "link").strip()
    value = (data.get("value") or "").strip()
    if not value:
        return jsonify({"error": "value is required"}), 400
    db = get_db()
    if not owns_subject(db, subject_id, current_user_id()):
        return jsonify({"error": "Subject not found"}), 404
    cur = db.execute(
        "INSERT INTO resources (subject_id, level2_id, type, value) VALUES (?, NULL, ?, ?)",
        (subject_id, r_type, value),
    )
    db.commit()
    return jsonify({"id": cur.lastrowid, "type": r_type, "value": value}), 201


@app.route("/api/resources/<int:resource_id>", methods=["DELETE"])
def delete_resource(resource_id):
    db = get_db()
    row = db.execute("SELECT subject_id FROM resources WHERE id = ?", (resource_id,)).fetchone()
    if not row or not owns_subject(db, row["subject_id"], current_user_id()):
        return jsonify({"error": "Not found"}), 404
    db.execute("DELETE FROM resources WHERE id = ?", (resource_id,))
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Dashboard API
# ---------------------------------------------------------------------------
def compute_streaks(db, uid):
    dates_rows = db.execute(
        "SELECT DISTINCT date FROM activity_log WHERE user_id = ? ORDER BY date DESC", (uid,)
    ).fetchall()
    dates = set(r["date"] for r in dates_rows)
    if not dates:
        return {"current_streak": 0, "longest_streak": 0}

    # current streak: count back from today (or yesterday if today has no activity yet)
    current_streak = 0
    cursor = datetime.utcnow().date()
    if cursor.strftime("%Y-%m-%d") not in dates:
        cursor -= timedelta(days=1)
    while cursor.strftime("%Y-%m-%d") in dates:
        current_streak += 1
        cursor -= timedelta(days=1)

    # longest streak overall
    sorted_dates = sorted(dates)
    longest_streak = 1
    run = 1
    for i in range(1, len(sorted_dates)):
        prev = datetime.strptime(sorted_dates[i - 1], "%Y-%m-%d").date()
        curr = datetime.strptime(sorted_dates[i], "%Y-%m-%d").date()
        if (curr - prev).days == 1:
            run += 1
        else:
            run = 1
        longest_streak = max(longest_streak, run)

    return {"current_streak": current_streak, "longest_streak": longest_streak}


def get_continue_item(db, uid):
    """Find the most sensible 'next thing to do' based on the most recent activity."""
    last_activity = db.execute(
        "SELECT level2_id, subject_id FROM activity_log WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (uid,),
    ).fetchone()

    def build_result(l2_row):
        info = db.execute(
            """SELECT l2.id AS level2_id, l2.name AS level2_name,
                      l1.id AS level1_id, l1.name AS level1_name,
                      s.id AS subject_id, s.name AS subject_name
               FROM level2 l2 JOIN level1 l1 ON l2.level1_id = l1.id
               JOIN subjects s ON l1.subject_id = s.id
               WHERE l2.id = ?""",
            (l2_row["id"],),
        ).fetchone()
        return row_to_dict(info)

    if last_activity:
        last_l2 = db.execute("SELECT level1_id FROM level2 WHERE id = ?", (last_activity["level2_id"],)).fetchone()
        if last_l2:
            # next incomplete item in the same level1
            nxt = db.execute(
                "SELECT id FROM level2 WHERE level1_id = ? AND done = 0 ORDER BY sort_order, id LIMIT 1",
                (last_l2["level1_id"],),
            ).fetchone()
            if nxt:
                return build_result(nxt)

        # next incomplete item anywhere in the same subject
        nxt = db.execute(
            """SELECT l2.id FROM level2 l2 JOIN level1 l1 ON l2.level1_id = l1.id
               WHERE l1.subject_id = ? AND l2.done = 0 ORDER BY l1.sort_order, l2.sort_order, l2.id LIMIT 1""",
            (last_activity["subject_id"],),
        ).fetchone()
        if nxt:
            return build_result(nxt)

    # fallback: first incomplete item in the most recently touched subject with any incomplete work
    nxt = db.execute(
        """SELECT l2.id FROM level2 l2
           JOIN level1 l1 ON l2.level1_id = l1.id
           JOIN subjects s ON l1.subject_id = s.id
           WHERE l2.done = 0 AND s.user_id = ?
           ORDER BY s.pinned DESC, s.created_at DESC, l1.sort_order, l2.sort_order, l2.id LIMIT 1""",
        (uid,),
    ).fetchone()
    if nxt:
        return build_result(nxt)
    return None


@app.route("/api/dashboard", methods=["GET"])
def dashboard():
    db = get_db()
    uid = current_user_id()
    total_subjects = db.execute(
        "SELECT COUNT(*) AS c FROM subjects WHERE user_id = ?", (uid,)
    ).fetchone()["c"]
    overall = overall_progress(db, uid)
    streaks = compute_streaks(db, uid)

    subject_rows = db.execute(
        """SELECT s.*, c.name AS category_name FROM subjects s
           JOIN categories c ON s.category_id = c.id
           WHERE s.user_id = ? ORDER BY s.pinned DESC, s.created_at DESC""",
        (uid,),
    ).fetchall()
    active_subjects = []
    for s in subject_rows:
        d = row_to_dict(s)
        d["progress"] = subject_progress(db, s["id"])
        d["last_studied"] = subject_last_studied(db, s["id"])
        active_subjects.append(d)

    badge_rows = db.execute(
        """SELECT b.*, s.name AS subject_name, l1.name AS level1_name
           FROM badges b
           JOIN subjects s ON b.subject_id = s.id
           JOIN level1 l1 ON b.level1_id = l1.id
           WHERE b.user_id = ?
           ORDER BY b.earned_date DESC, b.id DESC LIMIT 5""",
        (uid,),
    ).fetchall()
    recent_badges = [row_to_dict(r) for r in badge_rows]

    flagged_rows = db.execute(
        """SELECT l2.id AS level2_id, l2.name AS level2_name,
                  l1.id AS level1_id, l1.name AS level1_name,
                  s.id AS subject_id, s.name AS subject_name
           FROM level2 l2
           JOIN level1 l1 ON l2.level1_id = l1.id
           JOIN subjects s ON l1.subject_id = s.id
           WHERE l2.flagged = 1 AND s.user_id = ?
           ORDER BY l2.id DESC LIMIT 8""",
        (uid,),
    ).fetchall()
    flagged_items = [row_to_dict(r) for r in flagged_rows]

    continue_item = get_continue_item(db, uid)

    # activity calendar for last 90 days
    since = (datetime.utcnow().date() - timedelta(days=90)).strftime("%Y-%m-%d")
    activity_rows = db.execute(
        """SELECT date, COUNT(*) AS count FROM activity_log
           WHERE date >= ? AND user_id = ? GROUP BY date""",
        (since, uid),
    ).fetchall()
    activity_calendar = {r["date"]: r["count"] for r in activity_rows}

    category_count = db.execute(
        "SELECT COUNT(*) AS c FROM categories WHERE user_id = ?", (uid,)
    ).fetchone()["c"]

    return jsonify(
        {
            "total_subjects": total_subjects,
            "total_categories": category_count,
            "overall_progress": overall,
            "streaks": streaks,
            "active_subjects": active_subjects,
            "recent_badges": recent_badges,
            "activity_calendar": activity_calendar,
            "flagged_items": flagged_items,
            "continue_item": continue_item,
        }
    )


# ---------------------------------------------------------------------------
# Analytics API
# ---------------------------------------------------------------------------
@app.route("/api/analytics", methods=["GET"])
def analytics():
    db = get_db()
    uid = current_user_id()

    # completions per day, last 30 days
    since = (datetime.utcnow().date() - timedelta(days=30)).strftime("%Y-%m-%d")
    daily_rows = db.execute(
        """SELECT date, COUNT(*) AS count FROM activity_log
           WHERE date >= ? AND user_id = ? GROUP BY date ORDER BY date""",
        (since, uid),
    ).fetchall()
    daily_completions = [{"date": r["date"], "count": r["count"]} for r in daily_rows]

    # per-subject breakdown
    subject_rows = db.execute(
        """SELECT s.*, c.name AS category_name FROM subjects s
           JOIN categories c ON s.category_id = c.id WHERE s.user_id = ?""",
        (uid,),
    ).fetchall()
    subject_breakdown = []
    for s in subject_rows:
        prog = subject_progress(db, s["id"])
        subject_breakdown.append(
            {
                "id": s["id"],
                "name": s["name"],
                "category_name": s["category_name"],
                "progress": prog,
            }
        )

    # per-category breakdown
    category_rows = db.execute("SELECT * FROM categories WHERE user_id = ?", (uid,)).fetchall()
    category_breakdown = []
    for c in category_rows:
        row = db.execute(
            """SELECT COUNT(l2.id) AS total, SUM(l2.done) AS completed
               FROM level2 l2
               JOIN level1 l1 ON l2.level1_id = l1.id
               JOIN subjects s ON l1.subject_id = s.id
               WHERE s.category_id = ?""",
            (c["id"],),
        ).fetchone()
        total = row["total"] or 0
        completed = row["completed"] or 0
        category_breakdown.append(
            {
                "name": c["name"],
                "progress": {
                    "completed": completed,
                    "total": total,
                    "percent": calc_progress(completed, total),
                },
            }
        )

    total_badges = db.execute(
        "SELECT COUNT(*) AS c FROM badges WHERE user_id = ?", (uid,)
    ).fetchone()["c"]

    return jsonify(
        {
            "daily_completions": daily_completions,
            "subject_breakdown": subject_breakdown,
            "category_breakdown": category_breakdown,
            "total_badges": total_badges,
        }
    )


# ---------------------------------------------------------------------------
# Search API — matches subject names, level1 names, and level2 names.
# ---------------------------------------------------------------------------
@app.route("/api/search", methods=["GET"])
def search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"results": []})
    like = f"%{q}%"
    db = get_db()
    uid = current_user_id()

    results = []

    subj_rows = db.execute(
        """SELECT s.id AS subject_id, s.name AS subject_name, c.name AS category_name
           FROM subjects s JOIN categories c ON s.category_id = c.id
           WHERE s.name LIKE ? AND s.user_id = ? LIMIT 8""",
        (like, uid),
    ).fetchall()
    for r in subj_rows:
        results.append(
            {
                "type": "subject",
                "subject_id": r["subject_id"],
                "subject_name": r["subject_name"],
                "category_name": r["category_name"],
                "label": r["subject_name"],
            }
        )

    l1_rows = db.execute(
        """SELECT l1.id AS level1_id, l1.name AS level1_name, s.id AS subject_id,
                  s.name AS subject_name, s.level1_label AS level1_label
           FROM level1 l1 JOIN subjects s ON l1.subject_id = s.id
           WHERE l1.name LIKE ? AND s.user_id = ? LIMIT 8""",
        (like, uid),
    ).fetchall()
    for r in l1_rows:
        results.append(
            {
                "type": "level1",
                "subject_id": r["subject_id"],
                "subject_name": r["subject_name"],
                "level1_id": r["level1_id"],
                "label": r["level1_name"],
                "context_label": r["level1_label"],
            }
        )

    l2_rows = db.execute(
        """SELECT l2.id AS level2_id, l2.name AS level2_name, l1.id AS level1_id,
                  s.id AS subject_id, s.name AS subject_name, s.level2_label AS level2_label
           FROM level2 l2
           JOIN level1 l1 ON l2.level1_id = l1.id
           JOIN subjects s ON l1.subject_id = s.id
           WHERE l2.name LIKE ? AND s.user_id = ? LIMIT 10""",
        (like, uid),
    ).fetchall()
    for r in l2_rows:
        results.append(
            {
                "type": "level2",
                "subject_id": r["subject_id"],
                "subject_name": r["subject_name"],
                "level1_id": r["level1_id"],
                "level2_id": r["level2_id"],
                "label": r["level2_name"],
                "context_label": r["level2_label"],
            }
        )

    return jsonify({"results": results})


# ---------------------------------------------------------------------------
# Resources API (aggregate view across all subjects)
# ---------------------------------------------------------------------------
@app.route("/api/resources", methods=["GET"])
def all_resources():
    db = get_db()
    rows = db.execute(
        """SELECT r.*, l2.name AS level2_name, l1.name AS level1_name,
                  s.name AS subject_name, s.id AS subject_id
           FROM resources r
           JOIN subjects s ON r.subject_id = s.id
           LEFT JOIN level2 l2 ON r.level2_id = l2.id
           LEFT JOIN level1 l1 ON l2.level1_id = l1.id
           WHERE s.user_id = ?
           ORDER BY r.id DESC""",
        (current_user_id(),),
    ).fetchall()
    return jsonify([row_to_dict(r) for r in rows])


if __name__ == "__main__":
    db_compat.init_schema()
    port = int(os.environ.get("PORT", 5001))
    is_production = os.environ.get("RENDER") is not None
    app.run(host="0.0.0.0", port=port, debug=not is_production)
else:
    # Imported by a WSGI server (e.g. gunicorn) — still make sure the DB is ready.
    db_compat.init_schema()
