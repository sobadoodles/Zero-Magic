"""Transactional SQLite snapshots for this small, single-worker workspace.

Every mutating route and approval is one transaction. In-process snapshots keep
compatibility with the existing card rules; SQLite is the durable source on boot.
Do not run multiple Uvicorn workers against this snapshot implementation.
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from copy import deepcopy
from functools import wraps
from pathlib import Path
from threading import RLock, local

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("ZERO_MAGIC_DB", str(ROOT / "data" / "zero_magic.sqlite3")))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
lock = RLock()
_local = local()


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connection():
    conn = sqlite3.connect(DB_PATH, timeout=15, factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


with connection() as db:
    db.executescript('''
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS cards (id INTEGER PRIMARY KEY, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS people (id INTEGER PRIMARY KEY, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS comments (id INTEGER PRIMARY KEY, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS proposals (id TEXT PRIMARY KEY, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS prds (id TEXT PRIMARY KEY, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS prd_revisions (prd_id TEXT NOT NULL, revision INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY(prd_id,revision));
    CREATE TABLE IF NOT EXISTS prd_generation_requests (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, started_at REAL NOT NULL, active INTEGER NOT NULL);
    CREATE INDEX IF NOT EXISTS prd_requests_user ON prd_generation_requests(user_id,started_at);
    CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL, person_id INTEGER NOT NULL UNIQUE REFERENCES people(id),
      is_admin INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS sessions (
      token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS invitations (
      token_hash TEXT PRIMARY KEY, person_id INTEGER NOT NULL REFERENCES people(id),
      expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS login_attempts (scope TEXT NOT NULL, attempted_at REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS attempts_scope ON login_attempts(scope, attempted_at);
    ''')


def load_table(name):
    with connection() as db:
        return {row["id"]: json.loads(row["data"]) for row in db.execute(f"SELECT * FROM {name} ORDER BY id")}


cards = load_table("cards")
people = load_table("people")
comments = load_table("comments")
proposals = load_table("proposals")
prds = load_table("prds")
projects = load_table("projects")


class Counter:
    def __init__(self, value=1):
        self.value = value
    def __next__(self):
        value = self.value
        self.value += 1
        return value
    def __iter__(self):
        return self


def counter(name, records):
    with connection() as db:
        row = db.execute("SELECT value FROM counters WHERE name=?", (name,)).fetchone()
    return Counter(max(max(records, default=0) + 1, row[0] if row else 1))


card_ids = counter("cards", cards)
comment_ids = counter("comments", comments)
person_ids = counter("people", people)


def snapshot():
    return deepcopy((cards, people, comments, proposals, card_ids, comment_ids, person_ids, prds, projects))


def restore(data):
    global card_ids, comment_ids, person_ids
    for current, old in zip((cards, people, comments, proposals), data[:4]):
        current.clear()
        current.update(old)
    card_ids, comment_ids, person_ids = data[4:7]
    prds.clear()
    prds.update(data[7])
    projects.clear()
    projects.update(data[8])


def flush(db):
    # Small-workspace unit of work: update snapshots atomically; never persist
    # passwords or tokens in entity JSON. Separate credential tables below.
    for table, records in (("people", people), ("cards", cards), ("comments", comments), ("proposals", proposals), ("prds", prds), ("projects", projects)):
        db.executemany(f"INSERT INTO {table}(id,data) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                       [(key, json.dumps(value, ensure_ascii=False)) for key, value in records.items()])
        existing = {row[0] for row in db.execute(f"SELECT id FROM {table}")}
        db.executemany(f"DELETE FROM {table} WHERE id=?", [(key,) for key in existing - records.keys()])
    db.execute("DELETE FROM prd_revisions WHERE prd_id NOT IN (SELECT id FROM prds)")
    for doc in prds.values():
        db.execute("INSERT OR IGNORE INTO prd_revisions VALUES (?,?,?)", (doc["id"],doc["revision"],json.dumps(doc,ensure_ascii=False)))
    for name, iterator in (("cards", card_ids), ("comments", comment_ids), ("people", person_ids)):
        db.execute("INSERT INTO counters VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                   (name, iterator.value))


@contextmanager
def transaction():
    """Nested route calls share one SQLite commit, including approval receipts."""
    with lock:
        if getattr(_local, "db", None) is not None:
            yield _local.db
            return
        before = snapshot()
        db = connection()
        try:
            db.execute("BEGIN IMMEDIATE")
            _local.db = db
            yield db
            flush(db)
            db.commit()
        except BaseException:
            db.rollback()
            restore(before)
            raise
        finally:
            _local.db = None
            db.close()


def synchronized(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with transaction():
            return deepcopy(function(*args, **kwargs))
    return wrapped
