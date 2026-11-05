"""Local recovery only. Stop the server; enter passwords privately, not as arguments."""
import getpass
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from app import storage
from app.auth import hash_password, normalized_username
username=normalized_username(input("Account username: "))
with storage.connection() as db:
    row=db.execute("SELECT id FROM users WHERE username=?",(username,)).fetchone()
    if not row:raise SystemExit("Account not found.")
password=getpass.getpass("New password (12–128 characters): ")
confirm=getpass.getpass("Repeat password: ")
if password!=confirm or not 12<=len(password)<=128:raise SystemExit("Passwords must match and have 12–128 characters.")
with storage.connection() as db:
    db.execute("UPDATE users SET password_hash=? WHERE id=?",(hash_password(password),row[0]))
    db.execute("DELETE FROM sessions WHERE user_id=?",(row[0],))
print("Password reset. All previous sessions for this account are revoked.")
