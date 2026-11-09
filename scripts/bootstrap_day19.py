"""Bootstrap an isolated Day-19 eval environment through the REAL app routes.

Creates a throwaway SQLite DB, an owner, a board (project), ingests the reference
PRD via POST /api/v1/boards/{id}/documents (exercising the pending->processing->ready
lifecycle), and runs embeddings so semantic mode also works. Writes connection info
to a JSON file the eval harness consumes. Nothing touches the real data/ DB.
"""
import os, sys, base64, json, tempfile
from pathlib import Path

ROOT = Path(r"C:\Zero Magic Project")
sys.path.insert(0, str(ROOT))

db = Path(tempfile.mkdtemp(prefix="day19-")) / "workspace.sqlite3"
os.environ["ZERO_MAGIC_DB"] = str(db)
os.environ["ALLOWED_HOSTS"] = "localhost,127.0.0.1,testserver"
os.environ["PYTHONIOENCODING"] = "utf-8"

from fastapi.testclient import TestClient
from app.main import app
from app import storage

USER, PASS, NAME = "day19eval", "day19-eval-passphrase-1", "Day19 Evaluator"

c = TestClient(app)
r = c.post("/api/v1/auth/setup", json={"username": USER, "password": PASS, "name": NAME})
assert r.status_code == 201, r.text

board = c.post("/api/v1/projects", json={"name": "ZM Reference PRD", "color": "teal"})
assert board.status_code == 201, board.text
bid = board.json()["id"]

pdf = Path(r"C:\Users\Sadesgi\Downloads\Zero Magic Reference PRD.pdf").read_bytes()
up = c.post(f"/api/v1/boards/{bid}/documents", json={
    "filename": "Zero Magic Reference PRD.pdf",
    "content_base64": base64.b64encode(pdf).decode()})
assert up.status_code == 201, up.text
doc = up.json()["document"]
print("ingest ->", doc["status"], "| chunks:", doc["chunk_count"],
      "| pages:", doc["page_count"], "| attempts:", doc["attempts"])
assert doc["status"] == "ready", doc

# Embed for semantic mode (real multilingual MiniLM; cached model).
emb = c.post("/api/v1/knowledge/embed", json={})
print("embed ->", emb.json().get("embedded", emb.json().get("message")))

info = {"db": str(db), "base_note": "run uvicorn with ZERO_MAGIC_DB=this db",
        "board_id": bid, "user": USER, "password": PASS,
        "documents": doc["chunk_count"]}
out = Path(os.environ.get("DAY19_INFO", str(ROOT / "eval" / "day19" / "env.json")))
out.write_text(json.dumps(info, indent=2), encoding="utf-8")
print("connection info ->", out)
print("DB:", db)
