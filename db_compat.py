"""
Database compatibility layer.

- If a DATABASE_URL environment variable is set (Render + Supabase/Neon
  Postgres), every connection talks to that Postgres database, so data
  survives restarts and free-tier sleep/spin-down.
- If DATABASE_URL is not set (running locally via "Start LearnFlow.command"),
  everything falls back to the local database.db SQLite file exactly like
  before — nothing changes for local use.

The rest of app.py always writes plain "?"-style queries and reads rows with
row["column"], the same way for both databases. This module is the only
place that knows which database is actually in use.
"""
import os
import re
import sqlite3

DATABASE_URL = os.environ.get("DATABASE_URL")
USING_POSTGRES = bool(DATABASE_URL)

if USING_POSTGRES:
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool

    # Render/Supabase/Neon URLs are usually postgres:// — psycopg2 needs
    # postgresql://
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]

    # Opening a brand-new connection to a remote database (TCP + SSL
    # handshake + auth) on every single request is the single biggest
    # cause of the site feeling slow — it can easily add several hundred
    # ms to every request, even ones that don't touch much data. A small
    # pool keeps a handful of connections open and reuses them instead.
    _pool = psycopg2.pool.ThreadedConnectionPool(1, 5, DATABASE_URL)


_INSERT_RE = re.compile(r"^\s*INSERT\s+INTO\s+(\w+)", re.IGNORECASE)


class PGCursorWrapper:
    """Makes a psycopg2 cursor behave like a sqlite3 cursor for our code:
    exposes .lastrowid and returns rows that support both row["col"] and
    dict(row), same as sqlite3.Row."""

    def __init__(self, cursor):
        self._cursor = cursor
        self.lastrowid = None

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class PGConnWrapper:
    """Makes a psycopg2 connection behave like the sqlite3.Connection object
    the rest of app.py already expects: conn.execute(sql, params) and
    conn.commit(). Returns the underlying connection to the pool on close()
    instead of actually disconnecting, so the next request can reuse it."""

    def __init__(self, conn, from_pool=True):
        self._conn = conn
        self._from_pool = from_pool
        self._closed = False

    def execute(self, sql, params=()):
        pg_sql = sql.replace("?", "%s")
        # sqlite's LIKE is case-insensitive by default; Postgres's isn't —
        # use ILIKE so search behaves the same way for the person typing.
        pg_sql = re.sub(r"\bLIKE\b", "ILIKE", pg_sql, flags=re.IGNORECASE)

        m = _INSERT_RE.match(pg_sql)
        needs_id = bool(m) and "RETURNING" not in pg_sql.upper()
        if needs_id:
            pg_sql = pg_sql.rstrip().rstrip(";") + " RETURNING id"

        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(pg_sql, params)
        wrapped = PGCursorWrapper(cur)
        if needs_id:
            row = cur.fetchone()
            wrapped.lastrowid = row["id"] if row else None
        return wrapped

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._from_pool:
            try:
                # A connection left mid-transaction can't safely go back in
                # the pool for reuse.
                self._conn.rollback()
            except Exception:
                pass
            _pool.putconn(self._conn)
        else:
            self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._conn.commit()
        self.close()


def connect():
    """Returns a connection — Postgres if DATABASE_URL is set, otherwise the
    local SQLite file. Callers use it exactly the same way either way."""
    if USING_POSTGRES:
        raw = _pool.getconn()
        return PGConnWrapper(raw, from_pool=True)
    else:
        from app import DB_PATH  # local import avoids a circular import
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def IntegrityError():
    """The 'duplicate/constraint violation' exception class for whichever
    database is active, so app.py can write one except clause that works
    for both."""
    if USING_POSTGRES:
        return psycopg2.IntegrityError
    return sqlite3.IntegrityError


# A ready-to-use tuple for except clauses: except db_compat.IntegrityErrors:
IntegrityErrors = (psycopg2.IntegrityError,) if USING_POSTGRES else (sqlite3.IntegrityError,)


def insert_many(conn, table, columns, rows):
    """Inserts many rows in as few network round-trips as possible and
    returns the new ids in the same order as `rows`. Used for bulk import,
    where inserting one row at a time (one round-trip per row) is what made
    large syllabus pastes slow over a remote database."""
    if not rows:
        return []
    col_list = ", ".join(columns)
    if USING_POSTGRES:
        placeholders = ", ".join("(" + ", ".join(["%s"] * len(columns)) + ")" for _ in rows)
        flat_params = [v for row in rows for v in row]
        sql = f"INSERT INTO {table} ({col_list}) VALUES {placeholders} RETURNING id"
        cur = conn._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, flat_params)
        return [r["id"] for r in cur.fetchall()]
    else:
        placeholders = ", ".join(["?"] * len(columns))
        ids = []
        for row in rows:
            cur = conn.execute(f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})", row)
            ids.append(cur.lastrowid)
        return ids


def init_schema():
    """Creates all tables if they don't exist yet. Safe to call every time
    the app starts."""
    app_dir = os.path.dirname(os.path.abspath(__file__))
    if USING_POSTGRES:
        schema_path = os.path.join(app_dir, "schema_postgres.sql")
        raw = psycopg2.connect(DATABASE_URL)
        with raw:
            with raw.cursor() as cur:
                cur.execute(open(schema_path).read())
        raw.close()
    else:
        from app import DB_PATH, migrate_db
        schema_path = os.path.join(app_dir, "schema.sql")
        if not os.path.exists(DB_PATH):
            with sqlite3.connect(DB_PATH) as conn:
                conn.executescript(open(schema_path).read())
        else:
            migrate_db()
