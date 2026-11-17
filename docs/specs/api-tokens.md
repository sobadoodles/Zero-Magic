# Spec — API tokens (Bearer auth)

Closes the one genuine AuthN/AuthZ gap the Week-6 plan called out: *"Real API
tokens — Bearer for agents — is the one genuine gap; the app uses session
cookies."* Tokens let a script or CI runner act **as the workspace owner**
without a browser cookie, while preserving every existing design law.

## Scope

- Owner-minted, owner-revocable, per-account, hashed-at-rest, expiring Bearer
  tokens.
- Any route currently behind `Depends(require_user)` accepts a Bearer token in
  addition to the session cookie, with the same account identity and the same
  role checks.
- **Cookie-only admin surface**: `/auth/tokens` itself. A leaked Bearer token
  cannot mint replacements, so revocation actually revokes.
- Model / agent calls are unchanged. The assistant still has no confirm tool;
  nothing writes without the *human's* preview → approve → receipt.

## Data

New table, adjacent to `sessions` and `invitations` in `app/storage.py`:

```
api_tokens(
  id           INTEGER PK AUTOINCREMENT,
  token_hash   TEXT UNIQUE NOT NULL,   -- SHA-256 hex of the raw token
  owner_id     INTEGER NOT NULL REFERENCES users(id),
  label        TEXT NOT NULL,          -- 1–80 chars, trimmed, non-blank
  created_at   REAL NOT NULL,          -- unix seconds
  expires_at   REAL NOT NULL,          -- unix seconds, max +365 days
  revoked_at   REAL,                   -- NULL while active
  last_used_at REAL                    -- bumped on successful auth
)
```

Stored like sessions/invitations: dedicated rows written by `app/auth.py`,
never inside entity JSON, never in `flush()`.

## Lifecycle

1. **Mint** — owner (browser, cookie) `POST /api/v1/auth/tokens`
   `{label, expires_in_days?}` → `201` `{token, id, label, created_at,
   expires_at, note}`. The plaintext token is returned **once**; only its
   SHA-256 digest hits the DB, so a leak of `data/zero_magic.sqlite3` never
   reveals usable secrets.
2. **Present** — caller sends `Authorization: Bearer <token>` on any
   login-required route. `require_user` checks the cookie first, then the
   Bearer header. Both paths return the same `user_read` shape; a third field,
   `user["auth_via"]`, records `"session"` or `"token"` for logging and the
   cookie-only guard.
3. **Track** — every successful Bearer authentication updates
   `last_used_at`. Failed lookups do **not** update it, so a leaked token
   being probed is visible in `/auth/tokens`.
4. **Revoke** — `DELETE /api/v1/auth/tokens/{id}` (cookie + admin)
   sets `revoked_at`; the next Bearer call is 401. Double revoke is 409.
5. **Expire** — enforced at every auth check; expired rows are refused even
   if `revoked_at IS NULL`.
6. **Password reset** — `scripts/reset_password.py` (server stopped) also
   revokes every `api_tokens` row for that account alongside deleting
   sessions. Same "rehash kills all credentials" property as before.

## Limits

| Concern | Value |
|---|---|
| Active tokens per owner | **20**; the 21st mint is 409 "revoke one first" |
| Raw token length | 32-byte `secrets.token_urlsafe(32)` (~43 chars) |
| Header cap accepted | 200 chars (matching session cookie) |
| `expires_in_days` | 1–365, default 90 |
| Label | 1–80, trimmed, non-blank (visible-char rule not applied — labels are private to the owner) |

## Security properties (each locked by `tests/test_api_tokens.py`)

- A02 **Cryptographic failures** — tokens are `secrets`-random 32 bytes and
  stored as SHA-256 digests. The DB never contains the plaintext. Test:
  `test_token_string_is_never_stored`.
- A01 **Broken access control** — Bearer authenticates the *same* user, so
  `is_admin` still gates `/people` create, `/prds` edit (creator-only), etc.
  Members cannot mint tokens (no `require_admin` path). Test:
  `test_member_cannot_mint_or_list_tokens`.
- A01 **Escalation guard** — cookie-only admin routes
  (`require_cookie_admin`) reject Bearer calls with 403, so a leaked token
  cannot mint a replacement. Tests:
  `test_bearer_cannot_mint_another_token`, `test_bearer_cannot_revoke_itself_or_others`.
- A05 **Misconfiguration** — CSRF middleware skips the Origin / Sec-Fetch
  checks when `Authorization: Bearer` is present, because the credential is
  explicit, not ambient. Content-type enforcement stays in place for Bearer
  mutations. Tests: `test_bearer_allows_cross_origin_mutation`,
  `test_bearer_still_requires_application_json_for_mutations`.
- A07 **Auth failures** — expired and revoked tokens return a generic 401; no
  oracle reveals whether a hash existed. Test: `test_bearer_unknown_token_is_401`,
  `test_bearer_expired_is_refused`, `test_bearer_revoked_is_refused_immediately`.
- A08 **Data integrity** — reset_password revokes every outstanding token,
  matching the session-revocation guarantee. Test:
  `test_password_reset_revokes_every_token_for_that_account`.

## Design law preserved

**Nothing writes without an explicit, account-bound, expiring AI preview →
approval → idempotent receipt.** Bearer tokens do not change this. They carry
the *human owner's* authority to use the API the same way their browser can.
A leaked token can do what the owner can do — which is exactly why they are
20-cap, expiring, immediately revocable, and cookie-mint-only.

The assistant still has **no** Bearer token, no service account, and no
confirm tool. Agent writes go through `preview → approve → receipt` unchanged.

## Errors

| Status | Case | Body `detail` |
|---|---|---|
| 401 | No cookie, no Bearer | `Sign in to continue.` |
| 401 | Cookie present, expired | `Your session expired. Sign in again.` |
| 401 | Valid-length Bearer, unknown or expired or revoked | `Sign in to continue.` (unknown) / `Your session expired. Sign in again.` if cookie also present but expired — never reveals which factor failed |
| 403 | Bearer caller hits a cookie-only admin route | `Sign in with a browser session to manage API tokens.` |
| 403 | Non-admin (any path) hits `/auth/tokens` | `Only the workspace owner can manage API tokens.` |
| 404 | Revoke a `token_id` that does not belong to the caller | `Token not found.` |
| 409 | Revoke twice | `Token already revoked.` |
| 409 | 21st active token | `Only 20 active API tokens per account; revoke one first.` |
| 422 | Blank label / extra fields / out-of-range expiry | Pydantic array (existing contract) |

## Out of scope (recorded)

- **Scopes / per-token permissions.** A token carries the owner's full
  authority. Scopes would require a schema for `token_scopes` and a
  router-level allowlist; not needed at prototype scale, and any future
  design must not weaken the "cookie mint, Bearer cannot mint" guard.
- **Per-token rate limiting.** Bearer auth is 32 bytes of entropy; brute
  forcing is infeasible, so no throttling layer matches the `login_attempts`
  one for passwords. Revisit if we ever expose the API beyond localhost.
- **Browser UI in the Account dialog.** The three token routes are
  available via the Swagger UI at `/docs` and through curl; a small list +
  mint + revoke panel inside `account-dialog` is a follow-on slice. The
  current API contract is complete and shipped without it, matching the
  project's docs/specs/tests-together law (`PROJECT-KNOWLEDGE.md §12`).
- **Machine-to-machine clients without a human owner.** Every token is bound
  to a user; there is no service account concept.

## Testing surface

`tests/test_api_tokens.py` (22 tests) covers positive Bearer auth on read /
write / assistant / content-type, negative on bad / expired / revoked /
missing / short, escalation guard on mint and revoke, admin-only for members,
cap at 20, plaintext-never-in-DB, last-used tracking (success only), and the
reset-password cascade. Every OWASP bullet above links to the test name that
proves it.

## References

- `docs/auth-model.md` — the roles × endpoint-family matrix now includes the
  cookie / Bearer split for `/auth/tokens`.
- `architecture.md` — OWASP A01, A02, A05, A07, A08 rows updated for Bearer.
- `PROJECT-KNOWLEDGE.md §4.4 / §3.4` — the API surface count and auth section.
