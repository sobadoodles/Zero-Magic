"""Local accounts, hashed passwords, one-use invitations, and revocable cookies."""
import hashlib
import hmac
import os
import re
import secrets
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app import storage

router = APIRouter(prefix="/api/v1/auth", tags=["Accounts"])
COOKIE = "zero_magic_session"
SESSION_SECONDS = 30 * 86400
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=12, max_length=128)


class Setup(Credentials):
    person_id: int | None = Field(default=None, ge=1, strict=True)
    name: str = Field(min_length=1, max_length=100)


class AcceptInvite(Credentials):
    token: str = Field(min_length=20, max_length=128)


class InviteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    person_id: int = Field(ge=1, strict=True)


def normalized_username(value):
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9_.-]{3,40}", value):
        raise HTTPException(422, "Use 3–40 letters, numbers, dots, underscores, or hyphens for the username.")
    return value


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password):
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return f"scrypt${salt.hex()}${key.hex()}"


def verify_password(password, saved):
    try:
        _, salt, expected = saved.split("$")
        key = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(key.hex(), expected)
    except (ValueError, TypeError):
        return False


DUMMY_HASH = hash_password("not-a-real-password-constant")


def user_read(row):
    person = storage.people.get(row["person_id"])
    if not person:
        raise HTTPException(401, "Account profile is unavailable.")
    return {"id": row["id"], "username": row["username"], "person_id": row["person_id"],
            "name": person["name"], "is_admin": bool(row["is_admin"])}


def require_user(request: Request):
    token = request.cookies.get(COOKIE, "")
    if not token or len(token) > 200:
        raise HTTPException(401, "Sign in to continue.")
    with storage.lock, storage.connection() as db:
        row = db.execute("SELECT users.* FROM sessions JOIN users ON users.id=sessions.user_id WHERE token_hash=? AND expires>?",
                         (digest(token), time.time())).fetchone()
        if not row:
            raise HTTPException(401, "Your session expired. Sign in again.")
        return user_read(row)


def require_admin(user=Depends(require_user)):
    if not user["is_admin"]:
        raise HTTPException(403, "Only the workspace owner can manage logins and team members.")
    return user


def issue_session(db, response, user_id):
    token = secrets.token_urlsafe(32)
    db.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
    db.execute("INSERT INTO sessions VALUES (?,?,?)", (digest(token), user_id, time.time() + SESSION_SECONDS))
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True, secure=COOKIE_SECURE,
                        samesite="strict", path="/")


@router.get("/status")
def status():
    with storage.lock, storage.connection() as db:
        needed = db.execute("SELECT count(*) FROM users").fetchone()[0] == 0
        return {"setup_required":needed,"existing_people":[{"id":p["id"],"name":p["name"]} for p in storage.people.values()] if needed else []}


@router.get("/me")
def me(user=Depends(require_user)):
    return user


@router.post("/setup", status_code=201)
def setup(payload: Setup, response: Response):
    username = normalized_username(payload.username)
    if not payload.name.strip():
        raise HTTPException(422, "Name cannot be blank.")
    password_hash = hash_password(payload.password)
    with storage.transaction() as db:
        if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            raise HTTPException(409, "Workspace owner already exists. Sign in instead.")
        if payload.person_id is not None:
            if payload.person_id not in storage.people:
                raise HTTPException(404, "Existing profile not found.")
            person_id = payload.person_id
        else:
            person_id = next(storage.person_ids)
            person = {"id": person_id, "name": payload.name.strip(), "skills": [], "responsibility": ""}
            storage.people[person_id] = person
        # Flush before the foreign-key reference is created.
        storage.flush(db)
        user_id = db.execute("INSERT INTO users(username,password_hash,person_id,is_admin,created_at) VALUES (?,?,?,1,?)",
                             (username, password_hash, person_id, time.time())).lastrowid
        issue_session(db, response, user_id)
        return user_read(db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())


@router.post("/login")
def login(payload: Credentials, request: Request, response: Response):
    username = normalized_username(payload.username)
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    # Persist limits across restarts; return generic error for unknown usernames.
    with storage.lock, storage.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM login_attempts WHERE attempted_at < ?", (now-900,))
        if db.execute("SELECT count(*) FROM login_attempts WHERE scope IN (?,?)", ("ip:"+ip, "user:"+username)).fetchone()[0] >= 20:
            raise HTTPException(429, "Too many attempts. Wait 15 minutes and try again.")
        row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        valid = verify_password(payload.password, row["password_hash"] if row else DUMMY_HASH)
        if not row or not valid:
            db.executemany("INSERT INTO login_attempts VALUES (?,?)", [("ip:"+ip,now),("user:"+username,now)])
            db.commit()  # Keep rate-limit evidence even though the HTTP request fails.
            raise HTTPException(401, "Username or password is incorrect.")
        db.execute("DELETE FROM login_attempts WHERE scope=?", ("user:"+username,))
        issue_session(db, response, row["id"])
        return user_read(row)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response):
    with storage.lock, storage.connection() as db:
        db.execute("DELETE FROM sessions WHERE token_hash=?", (digest(request.cookies.get(COOKIE,"")),))
    response.delete_cookie(COOKIE, path="/", secure=COOKIE_SECURE, httponly=True, samesite="strict")


@router.post("/invitations", status_code=201)
def invite(payload: InviteInput, user=Depends(require_admin)):
    with storage.transaction() as db:
        if payload.person_id not in storage.people:
            raise HTTPException(404, "Person not found.")
        if db.execute("SELECT 1 FROM users WHERE person_id=?", (payload.person_id,)).fetchone():
            raise HTTPException(409, "This person already has a login.")
        db.execute("DELETE FROM invitations WHERE person_id=?", (payload.person_id,))
        token = secrets.token_urlsafe(32)
        expires = time.time()+48*3600
        db.execute("INSERT INTO invitations VALUES (?,?,?,0)", (digest(token),payload.person_id,expires))
        return {"token":token,"expires_at":datetime.fromtimestamp(expires,timezone.utc).isoformat()}


class InvitationToken(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=20, max_length=128)


@router.post("/invitation")
def invitation(payload: InvitationToken):
    token = payload.token
    with storage.lock, storage.connection() as db:
        row = db.execute("SELECT * FROM invitations WHERE token_hash=? AND used=0 AND expires>?", (digest(token),time.time())).fetchone()
        if not row:
            raise HTTPException(404, "Invitation is invalid, expired, or already used.")
        return {"name":storage.people[row["person_id"]]["name"]}


@router.post("/accept-invite", status_code=201)
def accept(payload: AcceptInvite, response: Response):
    username = normalized_username(payload.username)
    password_hash = hash_password(payload.password)
    with storage.transaction() as db:
        row = db.execute("SELECT * FROM invitations WHERE token_hash=? AND used=0 AND expires>?", (digest(payload.token),time.time())).fetchone()
        if not row:
            raise HTTPException(409, "Invitation is invalid, expired, or already used.")
        if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            raise HTTPException(409, "Username is already taken.")
        if db.execute("SELECT 1 FROM users WHERE person_id=?", (row["person_id"],)).fetchone():
            raise HTTPException(409, "This person already has a login.")
        user_id = db.execute("INSERT INTO users(username,password_hash,person_id,created_at) VALUES (?,?,?,?)",
                             (username,password_hash,row["person_id"],time.time())).lastrowid
        db.execute("UPDATE invitations SET used=1 WHERE token_hash=?", (digest(payload.token),))
        issue_session(db,response,user_id)
        return user_read(db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())
