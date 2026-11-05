"""Create a consistent private SQLite backup. Run from the project root."""
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parent.parent
load_dotenv(ROOT/".env")
source=Path(os.environ.get("ZERO_MAGIC_DB",str(ROOT/"data"/"zero_magic.sqlite3"))).resolve()
if not source.exists():raise SystemExit("No database yet. Start the app and set up your workspace first.")
target=ROOT/"backups"/("zero-magic-"+datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")+".sqlite3")
target.parent.mkdir(exist_ok=True)
with sqlite3.connect(source.as_uri()+"?mode=ro",uri=True) as src, sqlite3.connect(target) as dst:
    src.backup(dst)
print(f"Private backup saved: {target}")
print("Contains password hashes and sessions. Keep private; do not commit or share it.")
