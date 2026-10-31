# Passkeys as a Second Sign-in Factor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person can add passkeys and use one, instead of an authenticator code, as the second step after the
password; an admin (or a server command) can turn off someone's two-factor sign-in.

**Architecture:** Two new tables (`passkeys`, `webauthn_challenges`) and a `app/auth/passkeys.py` module wrapping
py_webauthn; a passkeys router for registration, listing and removal; `/api/auth/login` learns a `passkey`
assertion and a richer 401; the web app gets the "Confirm it's you" step, a Passkeys section in Profile, and an admin
action. Challenges live in Postgres (Valkey is optional).

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic, `webauthn==3.0.1` (py_webauthn), pytest; Next.js 16, React
19, `@simplewebauthn/browser@14.0.0`, vitest, Playwright (Chromium virtual authenticator).

**Spec:** `docs/superpowers/specs/2026-10-31-passkeys-design.md`

## Global Constraints

- Libraries pinned exactly: `webauthn==3.0.1` (backend/pyproject.toml via `uv add`), `"@simplewebauthn/browser": "14.0.0"` (no caret). Both are newer majors than most examples online: read the installed package's own docs/types (context7 or the package source) before using a call; the names below are the intent, not guaranteed signatures.
- RP ID = hostname of `settings.public_url`; expected origin = `scheme://host[:port]` of `settings.public_url`; RP name = `OrgSettings.name` or `"MegooColab"`.
- Creation: attestation `none`; resident key `preferred`; user verification `preferred`; exclude the person's existing credentials; algorithms ES256 (-7) and RS256 (-257). Request: `allowCredentials` = the person's passkeys; user verification `preferred`; timeout 120000 ms.
- Challenges: Postgres table, one row per (user, purpose), purposes `register` | `login` | `remove`; valid 5 minutes; deleted on use, success or failure; expired rows deleted whenever a new challenge is made.
- At most 10 passkeys per account → 409 `too_many_passkeys`. Passkey name 1–100 characters.
- Before the right password nothing reveals whether an account has passkeys (same `invalid_credentials` as today).
- Accounts with only an authenticator app keep getting exactly 401 `totp_required`.
- A failed passkey (login or removal) counts exactly like a wrong authenticator code: `guards.count("totp_account", …)`, `register_failed_login`, `auth.login_failed`. Ruling: the guard keeps its name `totp_account` (the spec's "renamed" is cosmetic; renaming moves Valkey keys and the setting) — same setting `rate_limit_totp_per_account`.
- Audit actions: `auth.passkey_added`, `auth.passkey_removed`, `auth.two_factor_reset`; `auth.login` gains `data={"second_factor": "totp" | "passkey"}` when one was used.
- Spec refinement (ruling): `UserOut` is reused by every screen that lists people, so it does **not** gain `passkey_count`. The profile reads `GET /api/auth/passkeys`; the sign-in step reads the 401; the admin page reads `GET /api/admin/users/two-factor`.
- Migrations generated against `megoo_migrate` only (`DEV_DATABASE_URL=postgresql+asyncpg://megoo:megoo@localhost:5433/megoo_migrate bash scripts/makemigration.sh "passkeys"`), constraints named, downgrade checked. Never run two pytest runs at once.
- Copy fixed by the spec (exact): "Confirm it's you"; "Your browser asks for your passkey: fingerprint, face, PIN or security key."; "Use passkey"; "Use an authenticator code instead"; "The passkey wasn't used. Try again, or use your authenticator code." (with an authenticator app) / "The passkey wasn't used. Try again." (passkeys only); "Add a passkey"; "Turn off two-factor sign-in"; email "<admin name> turned off two-factor sign-in for your MegooColab account. If you didn't ask for this, tell them."

## Review Focus

1. A passkey prompt dismissed, timed out or refused by the browser: the person stays on "Confirm it's you" with the message, can press **Use passkey** again, and (with an app) switch to the code — nothing signs in, nothing crashes. → Task 5 test `dismissed prompt shows the message and can retry`.
2. The same assertion sent twice (two tabs, a double click, a replay): the second is refused because its challenge is gone. → Task 2 test `test_assertion_cannot_be_used_twice`.
3. Another person's passkey offered for this account (a credential id that exists, but not theirs): refused. → Task 2 test `test_someone_elses_passkey_is_refused`.
4. A deactivated or invited account with a passkey and the right password: no second-step 401 and no challenge, just `invalid_credentials` as today. → Task 2 test `test_deactivated_account_gets_no_second_step`.
5. Removing the last passkey of an account without an authenticator app: two-factor sign-in goes off, and the next sign-in needs only the password. → Task 3 test `test_removing_the_last_passkey_turns_two_factor_off`.

---

### Task 1: Passkey data and registration

**Files:**
- Modify: `backend/pyproject.toml`, `backend/uv.lock` (`uv add webauthn==3.0.1`)
- Modify: `backend/app/auth/models.py` (add `Passkey`, `WebauthnChallenge`, `ChallengePurpose`)
- Create: `backend/migrations/versions/<rev>_passkeys.py` (generated)
- Create: `backend/app/auth/passkeys.py`, `backend/app/auth/passkeys_router.py`
- Modify: `backend/app/auth/schemas.py`, `backend/app/main.py` (include the router)
- Create: `backend/tests/auth/softkey.py` (a software authenticator for tests), `backend/tests/auth/test_passkeys.py`

**Interfaces:**
- Produces (models): `class ChallengePurpose(StrEnum): register, login, remove`; `Passkey` (table `passkeys`: id, user_id FK users ondelete CASCADE indexed, credential_id LargeBinary unique, public_key LargeBinary, sign_count int, transports JSONB list default [], aaguid String nullable, name String(100), created_at server now, last_used_at nullable); `WebauthnChallenge` (table `webauthn_challenges`: id, user_id FK CASCADE, purpose String(20), challenge LargeBinary, expires_at timestamptz; UniqueConstraint(user_id, purpose, name="uq_webauthn_challenges_user_purpose")).
- Produces (`app/auth/passkeys.py`):
  - `class PasskeyError(Exception)` with `.code: str` (`passkey_invalid`, `too_many_passkeys`, `passkey_exists`).
  - `def rp_id() -> str`, `def expected_origin() -> str`.
  - `async def new_challenge(db, user_id: uuid.UUID, purpose: ChallengePurpose) -> bytes`
  - `async def take_challenge(db, user_id: uuid.UUID, purpose: ChallengePurpose) -> bytes | None` (deletes the row; None when missing or expired)
  - `async def registration_options(db, user: User) -> dict` (JSON-ready options)
  - `async def register(db, user: User, name: str, credential: dict) -> Passkey`
  - `async def list_passkeys(db, user_id) -> list[Passkey]` (oldest first)
- Produces (schemas): `PasskeyOut(id, name, created_at, last_used_at)`; `PasskeyCreateIn(name: NoNulStr 1..100 stripped, credential: dict)`.
- Produces (routes, `prefix="/api/auth/passkeys"`, signed-in session): `GET ""` → `list[PasskeyOut]`; `POST /options` → options dict; `POST ""` → 201 `PasskeyOut` (audit `auth.passkey_added`, data `{"name"}`).
- Produces (tests): `tests/auth/softkey.py` — `class SoftKey(origin="http://localhost:8080", rp_id="localhost")` with `register(options: dict) -> dict` (a `PublicKeyCredential` JSON for `navigator.credentials.create`, attestation `none`, ES256 key) and `sign(options: dict, *, sign_count: int | None = None) -> dict` (an assertion JSON; `sign_count` defaults to an increasing counter), `.credential_id: bytes`. Built with `cryptography` (EC P-256) and `cbor2` (a py_webauthn dependency): authenticatorData = sha256(rp_id) ‖ flags (UP 0x01 | UV 0x04, plus AT 0x40 on registration) ‖ counter (4 bytes BE) ‖ on registration: aaguid (16 zero bytes) ‖ len(cred id) (2 bytes BE) ‖ cred id ‖ COSE key `{1: 2, 3: -7, -1: 1, -2: x, -3: y}`; clientDataJSON `{"type": "webauthn.create"|"webauthn.get", "challenge": <b64url>, "origin": origin, "crossOrigin": false}`; signature = DER ECDSA-SHA256 over authenticatorData ‖ sha256(clientDataJSON).

- [ ] **Step 1: Write the failing tests** in `tests/auth/test_passkeys.py`

```python
async def test_add_and_list_a_passkey(client, db):
    await login(client, await make_user(db))
    key = SoftKey()
    options = (await client.post("/api/auth/passkeys/options")).json()
    assert options["rp"]["id"] == "localhost" and options["attestation"] == "none"
    assert options["authenticatorSelection"]["residentKey"] == "preferred"
    r = await client.post("/api/auth/passkeys", json={"name": " Work laptop ", "credential": key.register(options)})
    assert r.status_code == 201 and r.json()["name"] == "Work laptop" and r.json()["last_used_at"] is None
    assert [p["name"] for p in (await client.get("/api/auth/passkeys")).json()] == ["Work laptop"]
    # audit row auth.passkey_added with {"name": "Work laptop"}

async def test_a_registration_with_a_used_or_wrong_challenge_fails(client, db):
    # same options/credential posted twice -> second 400 passkey_invalid (challenge gone)
    # a credential signed for origin "http://evil.example" -> 400 passkey_invalid

async def test_the_same_authenticator_is_not_added_twice(client, db):
    # options exclude the existing credential id; posting the same credential id again -> 409 passkey_exists

async def test_at_most_ten_passkeys(client, db):
    # ten added; the eleventh POST /options or POST -> 409 too_many_passkeys

async def test_someone_elses_list_is_never_shown(client, client_factory, db):
    # user B's GET /api/auth/passkeys is [] after user A adds one; no key material in PasskeyOut fields
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd backend && uv run pytest tests/auth/test_passkeys.py -q`
Expected: FAIL (`ModuleNotFoundError` / 404 on the routes)

- [ ] **Step 3: Implement** the models, the migration (generate, check `downgrade -1` / `upgrade head` on `megoo_migrate`), `passkeys.py` and the router. Use py_webauthn's registration options / verification functions and its JSON helpers (`options_to_json`, `parse_registration_credential_json` or the 3.x equivalents). `register` takes the `register` challenge (consumed even on failure), verifies with `expected_rp_id=rp_id()`, `expected_origin=expected_origin()`, stores credential id, public key, sign count, transports and aaguid; a library verification error → `PasskeyError("passkey_invalid")`.

- [ ] **Step 4: Run them to pass**, then `uv run pytest tests/auth -q`
Expected: PASS

- [ ] **Step 5: Commit** `feat(backend): passkeys can be added to an account`

### Task 2: Signing in with a passkey

**Files:**
- Modify: `backend/app/auth/router.py` (`LoginIn`, `login`), `backend/app/auth/passkeys.py`
- Test: `backend/tests/auth/test_passkey_login.py`

**Interfaces:**
- Consumes: Task 1's `new_challenge`, `take_challenge`, `list_passkeys`, `SoftKey`.
- Produces: `async def authentication_options(db, user: User, purpose: ChallengePurpose) -> dict`; `async def verify_assertion(db, user: User, credential: dict, purpose: ChallengePurpose) -> Passkey | None` (consumes the challenge; checks the credential belongs to `user`, origin, RP ID, counter; on success updates `sign_count` and `last_used_at`; a counter that goes backwards → None plus audit `auth.passkey_counter_rejected` target the user).
- Produces: `LoginIn.passkey: dict | None = None`. After the right password, active account, two-factor on, no factor sent:
  - passkeys → `JSONResponse(401, {"detail": "second_factor_required", "methods": ["passkey"] | ["passkey", "totp"], "passkey_options": {...}})`
  - only an app → `HTTPException(401, "totp_required")` (unchanged)
  With `passkey` sent: `verify_assertion(..., ChallengePurpose.login)`; failure is a wrong code (counting, lockout, audit, `invalid_credentials`). Success: `auth.login` with `{"second_factor": "passkey"}`; a code success records `{"second_factor": "totp"}`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_password_then_passkey_signs_in(client, client_factory, db):
    # user with a passkey (added via Task 1 routes) signs in from a fresh client:
    r = await other.post("/api/auth/login", json={"email": ..., "password": PW})
    assert r.status_code == 401 and r.json()["detail"] == "second_factor_required"
    assert r.json()["methods"] == ["passkey"]
    assert [c["id"] for c in r.json()["passkey_options"]["allowCredentials"]] == [b64url(key.credential_id)]
    r = await other.post("/api/auth/login", json={..., "passkey": key.sign(r.json()["passkey_options"])})
    assert r.status_code == 200
    # the passkey's last_used_at is set; audit auth.login data == {"second_factor": "passkey"}

async def test_with_an_app_too_both_methods_and_the_code_still_works(...):
    # methods == ["passkey", "totp"]; a correct totp_code alone (no passkey) signs in

async def test_only_an_app_is_unchanged(...):        # 401 detail == "totp_required", no passkey_options key
async def test_wrong_password_reveals_nothing(...):  # 401 invalid_credentials, no "methods"/"passkey_options"
async def test_assertion_cannot_be_used_twice(...):  # replaying the accepted assertion -> 401 invalid_credentials
async def test_someone_elses_passkey_is_refused(...):
    # B's assertion signed against A's login options (B's credential id) -> 401 invalid_credentials
async def test_a_counter_going_backwards_is_refused(...):  # key.sign(options, sign_count=0) after a use -> 401
async def test_failed_passkeys_count_like_wrong_codes(...):
    # settings.rate_limit_totp_per_account failures behind the right password -> next attempt 429 (as test_totp does)
async def test_deactivated_account_gets_no_second_step(...):  # status deactivated: 401 invalid_credentials, no challenge row
```

- [ ] **Step 2: Run to fail** — `uv run pytest tests/auth/test_passkey_login.py -q` → FAIL
- [ ] **Step 3: Implement** in `login`: after `password_ok`, load the passkeys (`list_passkeys`) only for an active account; choose the 401 per the Interfaces; when `body.passkey` is present use it instead of `totp_code` (a request with both uses the passkey). Keep the row lock and the existing commit-before-raise.
- [ ] **Step 4: Run** `uv run pytest tests/auth -q` → PASS
- [ ] **Step 5: Commit** `feat(backend): a passkey as the second sign-in step`

### Task 3: Removing a passkey

**Files:**
- Modify: `backend/app/auth/passkeys_router.py`, `backend/app/auth/schemas.py`
- Test: `backend/tests/auth/test_passkeys.py`

**Interfaces:**
- Consumes: Task 2's `authentication_options`, `verify_assertion`; `totp.verify`; `verify_password`.
- Produces: `POST /api/auth/passkeys/{id}/remove-options` → options (purpose `remove`, all the person's passkeys allowed); `DELETE /api/auth/passkeys/{id}` body `PasskeyRemoveIn(password: str, passkey: dict | None = None, totp_code: str | None = None)` → 204. Checks like `/totp/disable`: `guards.check("totp_account", …)` first; password and one second factor (passkey via `verify_assertion(..., remove)`, else `totp.verify`) must pass, else 400 `invalid_password_or_code`, counting only behind the right password; someone else's id → 404 `not_found`. Audit `auth.passkey_removed` `{"name"}`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_removing_needs_the_password_and_a_second_factor(client, db):
    # password only -> 400 invalid_password_or_code; wrong password + valid assertion -> 400
    # password + assertion from remove-options -> 204, list empty, audit auth.passkey_removed
async def test_removing_with_the_authenticator_code(...):  # password + totp_code -> 204
async def test_someone_elses_passkey_cannot_be_removed(...):  # 404 not_found
async def test_removing_the_last_passkey_turns_two_factor_off(client, client_factory, db):
    # no app: after removal, a fresh client's password-only login -> 200
```

- [ ] **Step 2: Run to fail** → FAIL; **Step 3: Implement**; **Step 4:** `uv run pytest tests/auth -q` → PASS
- [ ] **Step 5: Commit** `feat(backend): removing a passkey needs the password and a second factor`

### Task 4: Turning off someone's two-factor sign-in (admin and server command)

**Files:**
- Create: `backend/app/auth/two_factor.py`, `backend/app/cli.py`
- Modify: `backend/app/users/router.py`, `docs/install.md` (section 6 "HTTPS and domains": the host-name warning; section 14 "Troubleshooting": "Locked out of two-factor sign-in")
- Test: `backend/tests/users/test_two_factor_reset.py`

**Interfaces:**
- Produces: `async def has_two_factor(db, user: User) -> bool`; `async def two_factor_user_ids(db) -> list[uuid.UUID]`; `async def reset_two_factor(db, user: User, *, actor: User | None, via: Literal["admin", "cli"]) -> None` — clears `totp_enabled`/`totp_secret_enc`, deletes the person's passkeys and challenges, audit `auth.two_factor_reset` (actor id or None, target the user, `{"via": via}`), and, when `get_mailer(db)` returns a mailer, sends subject "Two-factor sign-in turned off" with the spec's body (the actor's name, or "An administrator" for the CLI); a mail failure is logged, never raised. Sessions are untouched.
- Produces: `GET /api/admin/users/two-factor` → `{"user_ids": [...]}` (admins); `POST /api/admin/users/{id}/reset-two-factor` → 204; 404 `not_found`; on oneself 409 `cannot_reset_own_two_factor`.
- Produces: `python -m app.cli reset-two-factor <email>` (argparse; exit 0 and prints "Two-factor sign-in turned off for <email>."; unknown email → exit 1, "No account with that email.").

- [ ] **Step 1: Write the failing tests**

```python
async def test_admin_turns_off_someones_two_factor(client, client_factory, db):
    # member with an app and a passkey; admin POST reset-two-factor -> 204;
    # member's GET /me totp_enabled False, their passkeys gone, password-only login 200,
    # audit auth.two_factor_reset {"via": "admin"}, OutboxMailer got the email naming the admin
async def test_listed_until_reset(...):           # GET two-factor user_ids contains the member, then not
async def test_not_on_oneself(...):               # 409 cannot_reset_own_two_factor
async def test_only_admins(...):                  # a manager -> 403
async def test_no_email_set_up_still_resets(...): # get_mailer None -> 204
async def test_cli_resets_by_email(db, capsys):   # app.cli.main(["reset-two-factor", email]) -> 0; unknown -> 1
```

- [ ] **Step 2: Run to fail** → FAIL; **Step 3: Implement** (inject the mailer the way `invite` does in `users/router.py`); **Step 4:** `uv run pytest tests/users tests/auth -q` → PASS
- [ ] **Step 5: Commit** `feat: an admin can turn off someone's two-factor sign-in`

### Task 5: "Confirm it's you" on the sign-in page

**Files:**
- Modify: `frontend/package.json`, `package-lock.json` (`npm install --save-exact @simplewebauthn/browser@14.0.0`)
- Modify: `frontend/src/lib/api.ts` (`ApiError` keeps the response body), `frontend/src/lib/errors.ts`
- Create: `frontend/src/lib/passkeys.ts`
- Modify: `frontend/src/app/(auth)/login/LoginForm.tsx`; run `npm run gen:api` after Tasks 1–4
- Test: `frontend/src/app/(auth)/__tests__/login.test.tsx`, `frontend/src/lib/__tests__/passkeys.test.ts`

**Interfaces:**
- Consumes: Task 2's 401 body.
- Produces: `class ApiError(status, detail, retryAfter = null, body: unknown = undefined)`.
- Produces (`lib/passkeys.ts`): `createPasskey(options: unknown): Promise<unknown>` and `getPasskey(options: unknown): Promise<unknown>` (the library's start-registration / start-authentication with `optionsJSON`); `isDismissed(err: unknown): boolean` (the browser's NotAllowedError/AbortError and the library's equivalents); `guessPasskeyName(userAgent: string): string` ("iPhone", "iPad", "Android phone", "Mac", "Windows", "Linux", else "Security key").
- Produces: `errors.ts` messages `passkey_invalid: "That passkey couldn't be checked. Try again."`, `too_many_passkeys: "You can have at most 10 passkeys. Remove one first."`, `passkey_exists: "This device already has a passkey for your account."`, `cannot_reset_own_two_factor: "Turn off your own two-factor sign-in from your profile."`.
- LoginForm: on 401 `second_factor_required` it shows the step (account header reused from the remembered-accounts work: the picked account, or the typed email), calls `getPasskey` once on entry, and on success posts `{email, password, passkey}`. **Use passkey** retries. The code link only when `methods` includes `"totp"`; it switches to today's code field. On `totp_required` behave as today.

- [ ] **Step 1: Write the failing tests** (mock `@/lib/passkeys` with `vi.mock`)

```tsx
it("after the password, asks for the passkey and signs in with it", async () => {
  // login 401 {detail:"second_factor_required", methods:["passkey"], passkey_options:{challenge:"c"}}
  // getPasskey resolves {id:"k"}; expect heading "Confirm it's you", getPasskey called with {challenge:"c"},
  // second login body has passkey {id:"k"} and the password; push("/")
});
it("offers the code only to someone with an authenticator app", ...);   // no "Use an authenticator code instead" for ["passkey"]
it("dismissed prompt shows the message and can retry", ...);
  // getPasskey rejects a dismissed error -> "The passkey wasn't used. Try again, or use your authenticator code."
  // click "Use passkey" -> getPasskey called a second time
it("switches to the code", ...);   // click the link -> "Authenticator code" field; submit sends totp_code
it("an app only is as before", ...);   // totp_required -> code field (existing test stays green)
```
`passkeys.test.ts`: `guessPasskeyName` cases; `isDismissed` true for `new DOMException("x", "NotAllowedError")`, false for `new Error("x")`.

- [ ] **Step 2: Run to fail** — `npx vitest run "src/app/(auth)" src/lib/__tests__/passkeys.test.ts` → FAIL
- [ ] **Step 3: Implement**; **Step 4: Run** the same → PASS, then `npx vitest run && npx tsc --noEmit && npm run lint`
- [ ] **Step 5: Commit** `feat(frontend): a passkey as the second sign-in step`

### Task 6: Passkeys in Profile › Two-factor sign-in

**Files:**
- Modify: `frontend/src/app/(app)/settings/profile/page.tsx` (the tab renders the existing `TwoFactor` as the "Authenticator app" section, then a new `PasskeysSection`)
- Create: `frontend/src/components/auth/PasskeysSection.tsx`
- Test: `frontend/src/components/auth/__tests__/PasskeysSection.test.tsx`

**Interfaces:**
- Consumes: Task 1/3 routes; Task 5's `createPasskey`, `getPasskey`, `guessPasskeyName`, `isDismissed`.
- Produces: `PasskeysSection({ totpEnabled }: { totpEnabled: boolean })` — query key `qk.passkeys()` (add to `lib/queries.ts`). List rows: name, "Added <date> · last used <date|never>", **Remove**. **Add a passkey** → `POST options` → `createPasskey` → name prompt (a small form prefilled with `guessPasskeyName(navigator.userAgent)`, max 100) → `POST`. **Remove** → a dialog with the password, then **Confirm with passkey** (remove-options → `getPasskey` → DELETE) or, if `totpEnabled`, an authenticator code field. A status line at the top of the tab: "Two-factor sign-in is on." when the app or any passkey is set up, else "Two-factor sign-in is off."

- [ ] **Step 1: Write the failing tests**: lists two passkeys with their dates and "never"; adding calls options → createPasskey → POST with the typed name; a dismissed create shows "The passkey wasn't added." and posts nothing; removing posts password + passkey; with an app the code path posts password + totp_code; the tab says on/off from app + passkeys.
- [ ] **Step 2: Run to fail**; **Step 3: Implement**; **Step 4: Run** `npx vitest run` + tsc + lint → PASS
- [ ] **Step 5: Commit** `feat(frontend): add and remove passkeys in Profile`

### Task 7: The admin's "Turn off two-factor sign-in"

**Files:**
- Modify: `frontend/src/app/(app)/admin/users/page.tsx`
- Test: `frontend/src/app/(app)/admin/users/__tests__/users.test.tsx`

**Interfaces:**
- Consumes: Task 4's routes.
- Produces: on each row in `two-factor` `user_ids` other than the admin's own: **Turn off two-factor sign-in** → the existing `ConfirmDialog` (`tone: "danger"`, title "Turn off two-factor sign-in for <name>?", text "Their authenticator app and all their passkeys are removed. They sign in with their password alone and can set two-factor sign-in up again from their profile.", ok "Turn off") → POST → refetch both queries.

- [ ] **Step 1: Write the failing tests**: the action shows only for listed people and never on oneself; confirming posts to `/api/admin/users/<id>/reset-two-factor`; cancelling posts nothing.
- [ ] **Step 2–4:** fail, implement, pass (`npx vitest run`, tsc, lint)
- [ ] **Step 5: Commit** `feat(frontend): admins can turn off someone's two-factor sign-in`

### Task 8: End to end with a virtual authenticator

**Files:**
- Create: `frontend/e2e/passkeys.spec.ts`

**Interfaces:**
- Consumes: everything above; `setupOrSignIn`, `ADMIN` from `e2e/helpers/auth.ts`.

- [ ] **Step 1: Write the test** (needs a fresh stack; creates the user `passkey@acme.io`): a CDP session (`WebAuthn.enable`, `WebAuthn.addVirtualAuthenticator` with `protocol: "ctap2", transport: "internal", hasResidentKey: true, hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true`); the admin creates the member via the API; the member signs in, adds a passkey named "E2E key" on Profile › Two-factor sign-in; signs out; signs in with the password and lands on the dashboard after "Confirm it's you"; the admin turns off their two-factor sign-in on Admin › Users; the member signs in with the password alone.
- [ ] **Step 2: Run** on a fresh stack: `docker compose -p megoo-e2e -f deploy/docker-compose.yml -f deploy/docker-compose.build.yml --env-file .superpowers/e2e.env up -d --build --wait`, then `cd frontend && npx playwright test` → all pass; `down -v` afterwards.
- [ ] **Step 3: Commit** `test(e2e): passkeys from adding to signing in to an admin reset`
