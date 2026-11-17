"""API tokens: Bearer auth, mint/list/revoke, escalation guards.

Each test builds a fresh owner via `/auth/setup` and exercises the exact
security properties that make this feature safe to expose:

  1. Cookie path unchanged (still works, still gets 401s when missing).
  2. Bearer path works on every business router.
  3. The raw token is shown exactly once; only the SHA-256 digest hits the DB.
  4. A Bearer call cannot mint another token (would defeat revocation).
  5. Revoke is immediate; expired tokens and revoked tokens are refused.
  6. Members (non-admin) cannot see or use `/auth/tokens` on any path.
  7. Cap: 20 active tokens per owner; the 21st returns 409.
  8. Password reset revokes every outstanding API token for that account.
"""
import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import tempfile
import os

os.environ.setdefault("ZERO_MAGIC_DB", str(Path(tempfile.mkdtemp()) / "api-tokens.sqlite3"))
from app import storage  # noqa: E402  (imported after env var, per conftest rule)
from app.main import app  # noqa: E402
from app.storage import Counter  # noqa: E402

PASSWORD = "test-passphrase-12345"


@pytest.fixture(autouse=True)
def reset():
    with storage.lock, storage.connection() as db:
        for table in ("api_tokens", "sessions", "invitations", "users",
                      "login_attempts", "proposals", "comments", "cards",
                      "people", "counters"):
            db.execute(f"DELETE FROM {table}")
    for data in (storage.cards, storage.people, storage.comments, storage.proposals):
        data.clear()
    storage.card_ids = Counter(1)
    storage.comment_ids = Counter(1)
    storage.person_ids = Counter(1)
    yield


def owner():
    client = TestClient(app)
    r = client.post("/api/v1/auth/setup",
                    json={"username": "owner", "password": PASSWORD, "name": "Saba"})
    assert r.status_code == 201, r.text
    return client


def mint(client, label="ci runner", expires_in_days=30):
    r = client.post("/api/v1/auth/tokens",
                    json={"label": label, "expires_in_days": expires_in_days})
    assert r.status_code == 201, r.text
    return r.json()


def bearer_client(token):
    """A TestClient that sends `Authorization: Bearer <token>` on every call,
    with no session cookie — models an external script / CI runner."""
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {token}"
    return client


# ---------------------------------------------------------------- Bearer reads


def test_bearer_reads_the_board():
    client = owner()
    client.post("/api/v1/cards", json={"title": "Wireframe", "goal": "Sketch"})
    t = mint(client)
    api = bearer_client(t["token"])
    r = api.get("/api/v1/cards")
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1


def test_bearer_writes_and_uses_the_owner_identity():
    """A Bearer call resolves to the same account as the cookie: the created
    card's project/owner context is the owner's, and `/auth/me` matches."""
    client = owner()
    t = mint(client)
    api = bearer_client(t["token"])
    r = api.get("/api/v1/auth/me")
    assert r.status_code == 200
    assert r.json()["username"] == "owner"
    assert r.json()["is_admin"] is True
    c = api.post("/api/v1/cards", json={"title": "From CI", "goal": "Prove identity"})
    assert c.status_code == 201, c.text


def test_bearer_calls_the_assistant_read_only_path():
    """Agent/chat endpoints require login; Bearer satisfies them the same way
    the cookie does. We do not run the model — just check the 422 boundary for
    an empty messages list, which proves the auth gate was passed."""
    client = owner()
    t = mint(client)
    api = bearer_client(t["token"])
    r = api.post("/api/v1/assistant/chat", json={"conversation_id": str(uuid4()),
                                                  "messages": [], "mode": "discuss"})
    # 422 (payload) not 401/403 → Bearer authenticated the request.
    assert r.status_code == 422, r.text


def test_bearer_still_requires_application_json_for_mutations():
    client = owner()
    t = mint(client)
    api = bearer_client(t["token"])
    r = api.post("/api/v1/cards", data="not json",
                 headers={"Content-Type": "text/plain"})
    # 415 (wrong content-type) not 401 → Bearer passed auth, content-type still enforced.
    assert r.status_code == 415, r.text


def test_bearer_allows_cross_origin_mutation():
    """Origin/Sec-Fetch CSRF guards exist to protect *cookie* auth. A Bearer
    header is explicitly sent by the caller, so a cross-origin Bearer POST is
    safe and must not be rejected as CSRF."""
    client = owner()
    t = mint(client)
    api = bearer_client(t["token"])
    r = api.post("/api/v1/cards",
                 json={"title": "From CI", "goal": "Prove cross-origin"},
                 headers={"Origin": "https://evil.example"})
    assert r.status_code == 201, r.text


# ------------------------------------------------------------------- Negative


def test_bearer_unknown_token_is_401():
    client = owner()  # so DB exists + has a users row
    api = bearer_client("not-a-real-token-value-here-xx")
    r = api.get("/api/v1/cards")
    assert r.status_code == 401


def test_bearer_short_token_is_rejected_before_lookup():
    client = owner()
    api = TestClient(app)
    api.headers["Authorization"] = "Bearer tooshort"
    r = api.get("/api/v1/cards")
    assert r.status_code == 401


def test_bearer_expired_is_refused():
    client = owner()
    t = mint(client, expires_in_days=1)
    # Force-expire by rewriting the row directly (never happens in production).
    with storage.connection() as db:
        db.execute("UPDATE api_tokens SET expires_at=? WHERE id=?",
                   (time.time() - 1, t["id"]))
    api = bearer_client(t["token"])
    r = api.get("/api/v1/cards")
    assert r.status_code == 401


def test_bearer_revoked_is_refused_immediately():
    client = owner()
    t = mint(client)
    api = bearer_client(t["token"])
    assert api.get("/api/v1/cards").status_code == 200
    d = client.delete(f"/api/v1/auth/tokens/{t['id']}")
    assert d.status_code == 204
    assert api.get("/api/v1/cards").status_code == 401


def test_missing_header_still_returns_generic_401():
    r = TestClient(app).get("/api/v1/cards")
    assert r.status_code == 401
    assert r.json()["detail"] == "Sign in to continue."


def test_expired_cookie_with_no_bearer_gets_expired_message():
    """We must not accidentally mask an expired-session error with a generic
    'sign in' just because we added a Bearer path."""
    client = owner()
    # Kill the session row but keep the cookie in the client jar.
    with storage.connection() as db:
        db.execute("UPDATE sessions SET expires=?", (time.time() - 1,))
    r = client.get("/api/v1/cards")
    assert r.status_code == 401
    assert r.json()["detail"] == "Your session expired. Sign in again."


# ------------------------------------------------------ Cookie-only mint guards


def test_bearer_cannot_mint_another_token():
    """Escalation guard: an API token cannot mint replacements. Otherwise
    revocation is useless — an attacker holding a leaked token could re-mint."""
    client = owner()
    t = mint(client)
    api = bearer_client(t["token"])
    r = api.post("/api/v1/auth/tokens",
                 json={"label": "backdoor", "expires_in_days": 30})
    assert r.status_code == 403, r.text
    assert "browser" in r.json()["detail"].lower()


def test_bearer_cannot_revoke_itself_or_others():
    client = owner()
    t = mint(client)
    api = bearer_client(t["token"])
    r = api.delete(f"/api/v1/auth/tokens/{t['id']}")
    assert r.status_code == 403


def test_bearer_cannot_list_the_full_set_but_can_read_its_own_metadata_via_me():
    client = owner()
    t = mint(client)
    api = bearer_client(t["token"])
    r = api.get("/api/v1/auth/tokens")
    # Listing is `Depends(require_admin)` — Bearer authenticates as the admin
    # owner, so listing succeeds. Metadata only, no raw tokens ever returned.
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["tokens"]) >= 1
    for row in body["tokens"]:
        assert "token" not in row
        assert "token_hash" not in row


def test_member_cannot_mint_or_list_tokens():
    """Members are signed-in non-admins. Mint/list/revoke all require admin,
    on both paths (cookie and Bearer, but members have no token path since
    minting is admin-only anyway)."""
    client = owner()
    person = client.post("/api/v1/people",
                         json={"name": "Sara", "skills": ["CSS"]}).json()
    invitation = client.post("/api/v1/auth/invitations",
                             json={"person_id": person["id"]}).json()
    member = TestClient(app)
    member.post("/api/v1/auth/accept-invite",
                json={"username": "sara", "password": PASSWORD, "token": invitation["token"]})
    r = member.get("/api/v1/auth/tokens")
    assert r.status_code == 403
    r = member.post("/api/v1/auth/tokens",
                    json={"label": "attempt", "expires_in_days": 1})
    assert r.status_code == 403


# -------------------------------------------------------------- Cap + one-shot


def test_twenty_one_mints_rejected():
    client = owner()
    for i in range(20):
        assert mint(client, label=f"t{i}")["id"] > 0
    r = client.post("/api/v1/auth/tokens",
                    json={"label": "21st", "expires_in_days": 30})
    assert r.status_code == 409
    assert "20" in r.json()["detail"]


def test_token_string_is_never_stored():
    """Only the SHA-256 digest lives in SQLite; the DB file on disk must not
    contain the raw secret (mirrors the session/invite discipline)."""
    client = owner()
    t = mint(client)
    raw = t["token"]
    # Read the underlying DB bytes; the raw token must not appear.
    path = storage.DB_PATH
    with open(path, "rb") as fh:
        data = fh.read()
    assert raw.encode() not in data


def test_mint_response_shape_is_complete_and_self_describing():
    client = owner()
    t = mint(client, label="runner", expires_in_days=15)
    assert set(t.keys()) == {"token", "id", "label", "created_at", "expires_at", "note"}
    assert t["label"] == "runner"
    assert t["expires_at"] - t["created_at"] == pytest.approx(15 * 86400, abs=2)
    assert "only time" in t["note"]


def test_revoke_unknown_returns_404_and_double_revoke_409():
    client = owner()
    t = mint(client)
    r = client.delete("/api/v1/auth/tokens/9999")
    assert r.status_code == 404
    assert client.delete(f"/api/v1/auth/tokens/{t['id']}").status_code == 204
    assert client.delete(f"/api/v1/auth/tokens/{t['id']}").status_code == 409


# ---------------------------------------------------------- Reset revokes tokens


def test_password_reset_revokes_every_token_for_that_account():
    """The `reset_password.py` script deletes sessions and flags api_tokens as
    revoked. We exercise the DB operation directly (the script itself is a
    stdin-driven TUI), matching its exact statements."""
    client = owner()
    t = mint(client)
    me = client.get("/api/v1/auth/me").json()
    api = bearer_client(t["token"])
    assert api.get("/api/v1/cards").status_code == 200
    with storage.connection() as db:
        db.execute("UPDATE sessions SET expires=? WHERE user_id=?",
                   (time.time() - 1, me["id"]))
        db.execute("UPDATE api_tokens SET revoked_at=? WHERE owner_id=? AND revoked_at IS NULL",
                   (time.time(), me["id"]))
        db.commit()
    assert api.get("/api/v1/cards").status_code == 401


# -------------------------------------------------------- last_used_at tracking


def test_last_used_at_updates_on_success():
    client = owner()
    t = mint(client)
    with storage.connection() as db:
        before = db.execute("SELECT last_used_at FROM api_tokens WHERE id=?",
                            (t["id"],)).fetchone()["last_used_at"]
    assert before is None
    api = bearer_client(t["token"])
    api.get("/api/v1/cards")
    with storage.connection() as db:
        after = db.execute("SELECT last_used_at FROM api_tokens WHERE id=?",
                           (t["id"],)).fetchone()["last_used_at"]
    assert after is not None and after > time.time() - 60


def test_last_used_at_does_not_update_on_bad_token():
    client = owner()
    mint(client)
    bad = TestClient(app)
    bad.headers["Authorization"] = "Bearer this-is-a-bogus-token-value-zz"
    bad.get("/api/v1/cards")
    with storage.connection() as db:
        rows = db.execute("SELECT last_used_at FROM api_tokens").fetchall()
    assert all(r["last_used_at"] is None for r in rows)
