# Valkey and Rate Limits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Valkey as a required service and use it to rate-limit sign-in, account pages, the general API, AI calls, git webhooks and WebSocket connects, with a clear "try again in N minutes" message and an admin status line.

**Architecture:** A small `app/ratelimit` package owns the Valkey client, fixed-window counters (`INCR` + `EXPIRE NX` in one transaction), the client-address rules and a 429 exception with its handler. A pure ASGI middleware applies the general per-credential and per-IP limits to every `/api` HTTP request; named limits are explicit calls inside the routes that own them (failures-only ones peek first and count after the endpoint fails). Every Valkey error fails open with a throttled warning.

**Tech Stack:** FastAPI, `valkey-py` (`valkey.asyncio`), Valkey server image, pytest against the dev Valkey, Next 16 / React 19 / Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-28-valkey-rate-limits-design.md`

## Global Constraints

- Valkey is **required** in production compose, dev compose, CI and the e2e stack; the backend starts when it is down (`depends_on: condition: service_started`).
- When Valkey is unreachable, every check **allows** the request; warnings are logged at most once a minute.
- 429 response: body `{"detail": "rate_limited", "retry_after": <int seconds ≥ 1>}` and header `Retry-After: <same int>`.
- Frontend copy: `Too many attempts. Try again in N minutes.` (N = ceil(seconds/60)), or `Too many attempts. Try again in N seconds.` when under a minute. Singular "1 minute" / "1 second".
- Defaults and `.env` names (windows fixed in code):

  | Limit name (code) | Setting / env | Default | Window | Counted per |
  |---|---|---|---|---|
  | `login_ip` | `RATE_LIMIT_LOGIN_PER_IP` | 30 | 15 min | client IP, failures only |
  | `totp_account` | `RATE_LIMIT_TOTP_PER_ACCOUNT` | 5 | 15 min | user id, wrong code after correct password |
  | `forgot_email` | `RATE_LIMIT_FORGOT_PER_EMAIL` | 3 | 1 h | lowercased email, every request |
  | `forgot_ip` | `RATE_LIMIT_FORGOT_PER_IP` | 10 | 1 h | client IP, every request |
  | `reset_ip`, `invite_ip`, `setup_ip` | `RATE_LIMIT_TOKEN_PAGES_PER_IP` | 10 | 1 h | client IP, failures only, separate counters |
  | `change_password_user` | `RATE_LIMIT_CHANGE_PASSWORD_PER_USER` | 5 | 15 min | user id, wrong current password |
  | `api_user` | `RATE_LIMIT_API_PER_USER` | 600 | 1 min | credential (see below) |
  | `api_ip` | `RATE_LIMIT_API_PER_IP` | 120 | 1 min | client IP: anonymous requests, plus 401s of credentialed ones |
  | `ai_user` | `RATE_LIMIT_AI_PER_USER` | 30 | 1 min | credential |
  | `webhook_connection` | `RATE_LIMIT_WEBHOOK_PER_CONNECTION` | 120 | 1 min | git connection id, valid signature only |
  | `ws_connect` | `RATE_LIMIT_WS_CONNECT` | 30 | 1 min | credential, else client IP |

- Credential subject: `tok:<sha256 hex of the raw bearer>` for any `Authorization: Bearer` (personal `mgc_` and run `mgr_` tokens alike), else `ses:<sha256 hex of the megoo_session cookie>`, else none. **Plan ruling:** the spec says a browser session counts per *user*; the middleware runs before any DB lookup, so it counts per *session* (one per signed-in browser). Cost if wrong: a person signed in on three browsers gets three 600/min budgets.
- Existing per-account lockout in `app/auth/service.py` (10 failures / 15 min, 423 `locked`) is unchanged and takes precedence over 429.
- Valkey keys: `{VALKEY_PREFIX}rl:{name}:{subject}:{window_index}`; audit-once marker `{VALKEY_PREFIX}rla:{name}:{subject}:{window_index}`. `VALKEY_PREFIX` default `megoo:`.
- Client IP: `CLIENT_IP_HEADER` (default empty). When set and the header holds one valid IP, use it; otherwise the address uvicorn resolved (`scope["client"][0]`). IPv6 is reduced to its /64 (`2001:db8:1:2::/64`); IPv4 as is.
- Audit: action `rate_limit.blocked`, `data={"limit": name, "ip": client_ip}`, `actor_id` when the route knows the user; once per counter per window.
- Image `valkey/valkey:8.1.3` (or the newest 8.x patch at least two weeks old; same tag everywhere); persistence off (`--save "" --appendonly no`); `--requirepass`.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Valkey goes down while the app runs (or is never reachable): every route works, nothing returns 500, the admin status says limits are off — Task 1 `test_valkey_down_allows_and_reports`, Task 2 `test_middleware_fails_open`.
2. Someone rotates fake bearer tokens or cookies to dodge the per-credential limit: their IP is blocked after `api_ip` 401s — Task 2 `test_fake_credentials_get_the_ip_blocked`.
3. Forty people sign in successfully from one office address: none is ever limited — Task 3 `test_successful_sign_ins_never_count`.
4. A stranger with only an email types wrong codes: the owner's two-factor budget is untouched — Task 3 `test_wrong_password_codes_do_not_count`.
5. A forged webhook flood at a real connection's URL: genuine deliveries still go through — Task 4 `test_forged_webhooks_do_not_use_the_connection_budget`.

---

### Task 1: Valkey client, counters, client address and the 429

**Files:**
- Create: `backend/app/ratelimit/__init__.py`, `backend/app/ratelimit/store.py`, `backend/app/ratelimit/limits.py`, `backend/app/ratelimit/clientip.py`
- Modify: `backend/app/core/config.py`, `backend/app/main.py` (exception handler), `backend/pyproject.toml` (+ `uv.lock`), `backend/tests/conftest.py`, `deploy/docker-compose.dev.yml`, `.github/workflows/ci.yml`, `Makefile` (dev exports), `README.md` (dev setup line)
- Test: `backend/tests/ratelimit/__init__.py`, `backend/tests/ratelimit/test_store.py`

**Interfaces:**
- Produces:
  - Settings: `valkey_url: str = "valkey://:megoo-dev-valkey@localhost:6379/0"`, `valkey_prefix: str = "megoo:"`, `client_ip_header: str = ""`, and one `rate_limit_*: int` per row of the table (defaults as listed).
  - `limits.Limit` — frozen dataclass `(name: str, max: int, window: int)`; `limits.get(name: str) -> Limit` builds it from settings (window seconds: 900 / 3600 / 60 per the table).
  - `store.Decision` — frozen dataclass `(allowed: bool, retry_after: int)`.
  - `async store.hit(limit: Limit, subject: str) -> Decision` — counts one and decides (count > max → not allowed).
  - `async store.peek(limit: Limit, subject: str) -> Decision` — decides without counting (count ≥ max → not allowed).
  - `async store.healthy() -> bool` — PING within 1 s.
  - `store.reset_client() -> None` — drops the cached client (tests).
  - `class RateLimited(Exception)` with `retry_after: int`, `limit: str`; `async store.raise_if_blocked(decision: Decision, limit: Limit, *, ip: str, subject: str, actor_id: uuid.UUID | None = None) -> None` returns when allowed, else writes the audit-once row and raises it.
  - `rate_limited_response(retry_after: int) -> JSONResponse` and an app exception handler for `RateLimited`.
  - `clientip.client_ip(scope_or_request) -> str`.

- [ ] **Step 1: Start the dev Valkey.** Add a `valkey` service to `deploy/docker-compose.dev.yml` (image per Global Constraints, port `6379:6379`, `command: ["valkey-server", "--requirepass", "megoo-dev-valkey", "--save", "", "--appendonly", "no"]`, healthcheck `valkey-cli -a megoo-dev-valkey ping`). Run `MSYS_NO_PATHCONV=1 docker compose -f deploy/docker-compose.dev.yml up -d --wait valkey`. Expected: container `megoocolab-dev-valkey-1` healthy.

- [ ] **Step 2: Write the failing tests** in `backend/tests/ratelimit/test_store.py`:

```python
LIMIT = Limit("t", max=3, window=60)

async def test_hit_allows_up_to_max_then_blocks():
    s = f"s-{uuid.uuid4()}"
    assert [ (await store.hit(LIMIT, s)).allowed for _ in range(4) ] == [True, True, True, False]
    blocked = await store.hit(LIMIT, s)
    assert 1 <= blocked.retry_after <= 60

async def test_peek_does_not_count():
    s = f"s-{uuid.uuid4()}"
    for _ in range(5):
        assert (await store.peek(LIMIT, s)).allowed
    for _ in range(3):
        await store.hit(LIMIT, s)
    assert not (await store.peek(LIMIT, s)).allowed

async def test_subjects_and_names_are_separate():
    s = f"s-{uuid.uuid4()}"
    for _ in range(3):
        await store.hit(LIMIT, s)
    assert (await store.hit(Limit("other", 3, 60), s)).allowed
    assert (await store.hit(LIMIT, s + "x")).allowed

async def test_valkey_down_allows_and_reports(monkeypatch):
    monkeypatch.setattr(get_settings(), "valkey_url", "valkey://:x@127.0.0.1:1/0")
    store.reset_client()
    assert (await store.hit(LIMIT, "s")) == Decision(True, 0)
    assert (await store.peek(LIMIT, "s")).allowed
    assert await store.healthy() is False

def test_client_ip_rules(monkeypatch):
    scope = {"type": "http", "client": ("10.0.0.5", 1), "headers": [(b"cf-connecting-ip", b"203.0.113.9")]}
    assert client_ip(scope) == "10.0.0.5"                       # header ignored unless configured
    monkeypatch.setattr(get_settings(), "client_ip_header", "CF-Connecting-IP")
    assert client_ip(scope) == "203.0.113.9"
    scope["headers"] = [(b"cf-connecting-ip", b"not-an-ip")]
    assert client_ip(scope) == "10.0.0.5"                       # invalid header → resolved address
    scope["headers"] = [(b"cf-connecting-ip", b"2001:db8:1:2:aaaa::1")]
    assert client_ip(scope) == "2001:db8:1:2::/64"

async def test_raise_if_blocked_audits_once_per_window(db):
    s = f"s-{uuid.uuid4()}"
    for _ in range(3):
        await store.hit(LIMIT, s)
    for _ in range(3):
        with pytest.raises(RateLimited) as e:
            await store.raise_if_blocked(await store.hit(LIMIT, s), LIMIT, ip="1.2.3.4", subject=s)
        assert e.value.retry_after >= 1
    rows = await audit_rows(db, "rate_limit.blocked")
    assert len(rows) == 1 and rows[0].data == {"limit": "t", "ip": "1.2.3.4"}
```

Add an autouse fixture in `backend/tests/conftest.py` that sets `get_settings().valkey_prefix` to `f"test:{uuid4()}:"` per test and calls `store.reset_client()` after, plus env defaults `VALKEY_URL=valkey://:megoo-dev-valkey@localhost:6379/0`.

- [ ] **Step 3: Run them to verify they fail.** `cd backend && uv run pytest tests/ratelimit -q`. Expected: FAIL on `ModuleNotFoundError: app.ratelimit`.

- [ ] **Step 4: Implement.** `uv add valkey` (check the `valkey.asyncio` API and the accepted URL schemes with Context7 `/valkey-io/valkey-py`; if `valkey://` is not accepted use `redis://` everywhere instead). `store.hit`: `window_index = int(now // window)`, key per Global Constraints, `MULTI: INCR key; EXPIRE key window NX`, `retry_after = max(1, (window_index + 1) * window - int(now))`. Every Valkey call is wrapped: socket/connection/timeout errors (1 s timeouts on the client) → `Decision(True, 0)` and a warning logged at most once per 60 s. `raise_if_blocked`: when not allowed, `SET rla-key 1 NX EX window`; if set, write the audit row in its own `SessionLocal()` and commit; then raise `RateLimited`. Register the handler in `create_app` returning the Global Constraints body and header. Settings fields as in Interfaces; CI gets a `valkey` service (same image, `--requirepass ci-valkey`) and `VALKEY_URL`; the Makefile's dev exports gain `VALKEY_URL`; README's dev section lists Valkey on `localhost:6379`.

- [ ] **Step 5: Run the tests.** `uv run pytest tests/ratelimit -q`. Expected: all pass. Then `uv run pytest -q -x` once (background, output to a file): Expected: green (the general limit is not wired yet).

- [ ] **Step 6: Commit** `feat(ratelimit): Valkey client, fixed-window counters, client address and 429`.

### Task 2: General API limits middleware

**Files:**
- Create: `backend/app/ratelimit/middleware.py`
- Modify: `backend/app/main.py` (add the middleware outermost, after CSRF registration so it runs first)
- Test: `backend/tests/ratelimit/test_middleware.py`

**Interfaces:**
- Consumes: Task 1 `store`, `limits`, `client_ip`, `rate_limited_response`.
- Produces: `middleware.RateLimitMiddleware(app)` (pure ASGI); `middleware.current_subject: ContextVar[str | None]` — the credential subject (or `ip:<addr>` for anonymous) of the current request, for Task 4's AI checks; `middleware.credential_subject(headers: Headers, cookies: Mapping[str, str]) -> str | None`.

Rules (HTTP scopes whose path starts with `/api/`; everything else passes through untouched):
1. Exempt: `/api/health`, and anonymous requests to `/api/git/webhooks/` (the route counts them, Task 4).
2. With a credential: `peek(api_ip, ip)` → 429 if blocked; then `hit(api_user, subject)` → 429 if blocked; run the app; if the response status is 401, `hit(api_ip, ip)`.
3. Without one: `hit(api_ip, ip)` → 429 if blocked.
4. Set `current_subject` (credential subject, else `ip:<addr>`) for the duration of the call.

- [ ] **Step 1: Write the failing tests** (lower the limits per test with `monkeypatch.setattr(get_settings(), "rate_limit_api_per_user", 5)` etc.):

```python
async def test_signed_in_user_is_limited_per_session(client, member):     # member: signed-in client fixture
    for _ in range(5):
        assert (await member.get("/api/auth/me")).status_code == 200
    r = await member.get("/api/auth/me")
    assert r.status_code == 429 and r.json()["detail"] == "rate_limited"
    assert int(r.headers["retry-after"]) == r.json()["retry_after"] >= 1

async def test_each_token_has_its_own_budget(client, member): ...       # two PATs: 5 each pass on GET /api/tokens/self
async def test_anonymous_calls_are_limited_per_ip(client): ...          # api_per_ip=5: 5× GET /api/setup/status pass, 6th 429
async def test_fake_credentials_get_the_ip_blocked(client):
    for i in range(5):
        r = await client.get("/api/projects", headers={"Authorization": f"Bearer mgc_fake{i}"})
        assert r.status_code == 401
    r = await client.get("/api/projects", headers={"Authorization": "Bearer mgc_fake99"})
    assert r.status_code == 429
async def test_health_and_webhooks_are_exempt(client): ...             # api_per_ip=1: 3× /api/health 200; anon webhook POSTs not 429 from the middleware
async def test_middleware_fails_open(client, member, monkeypatch): ...  # unreachable VALKEY_URL: 20 calls all 200
async def test_mcp_calls_count_per_token(client, mcp_token): ...        # api_per_user=3: 4th POST /api/mcp → 429
```

- [ ] **Step 2: Run them to verify they fail.** `uv run pytest tests/ratelimit/test_middleware.py -q`. Expected: FAIL (no 429s).
- [ ] **Step 3: Implement `RateLimitMiddleware`** per the rules above. The 401 check wraps `send` to read `http.response.start`'s status.
- [ ] **Step 4: Run the tests, then the whole backend suite** (background, to a file; the suite's own traffic must stay under the defaults — if a test legitimately exceeds 600/min on one session, raise the limit in that test, never globally). Expected: all pass.
- [ ] **Step 5: Commit** `feat(ratelimit): per-credential and per-IP API limits`.

### Task 3: Sign-in and account limits

**Files:**
- Modify: `backend/app/auth/router.py`, `backend/app/setup/router.py`
- Test: `backend/tests/ratelimit/test_auth_limits.py`

**Interfaces:**
- Consumes: Task 1 `store.hit/peek/raise_if_blocked`, `limits.get`, `client_ip`.

Per route (peek → 429 before any work; count after the failure; the existing 423 check stays before the TOTP limit):
- `POST /api/auth/login`: peek `login_ip`; on each `invalid_credentials` 401, hit `login_ip`. When the password is right, the account has two-factor and a code is given: peek `totp_account` (user id) → 429; a wrong code then hits `totp_account` (and still counts toward the existing lockout). `totp_required` is not a failure.
- `POST /api/auth/totp/enable`: peek, and hit `totp_account` on `invalid_code`. `POST /api/auth/totp/disable`: peek; hit only when the password was right and the code wrong.
- `POST /api/auth/forgot`: hit `forgot_ip` and `forgot_email` (lowercased) for every request, before the lookup; blocked → 429 (same for known and unknown emails).
- `POST /api/auth/reset` → `reset_ip`, `POST /api/auth/accept-invite` → `invite_ip`, `POST /api/setup` → `setup_ip`: peek; hit on `invalid_or_expired_token` / `already_set_up`.
- `POST /api/auth/change-password`: peek `change_password_user`; hit on `invalid_current_password`.

- [ ] **Step 1: Write the failing tests** (lower each limit in-test):

```python
async def test_failed_sign_ins_block_the_ip(client): ...              # login_per_ip=3: 3 wrong → 401; 4th (even right password) → 429
async def test_successful_sign_ins_never_count(client, member): ...   # login_per_ip=3: 10 right sign-ins all 200
async def test_lockout_still_wins(client, member): ...                # 10 wrong with login_per_ip high → 423 as before
async def test_wrong_codes_after_right_password_limit_the_account(client, totp_member): ...
    # totp_per_account=2: 2 wrong codes → 401; 3rd with the right code → 429
async def test_wrong_password_codes_do_not_count(client, totp_member): ...
    # 5 attempts wrong password + wrong code; then right password + right code → 200
async def test_forgot_limits_per_email_and_ip(client): ...            # forgot_per_email=2: 3rd for same email 429; other email 204; forgot_per_ip=3 → 4th 429
async def test_token_pages_count_failures(client): ...                # token_pages=2: 2 bad reset tokens 400, 3rd 429; invite counter separate
async def test_change_password_counts_wrong_current_password(client, member): ...
async def test_blocks_are_audited_once(client, db): ...               # 3 blocked logins → one rate_limit.blocked row, data limit=login_ip
```

- [ ] **Step 2: Run to verify they fail.** Expected: FAIL (no 429s).
- [ ] **Step 3: Implement** in the routes above. Every 429 here goes through `raise_if_blocked` with `actor_id` when the user is known.
- [ ] **Step 4: Run `tests/ratelimit` and `tests/auth tests/setup`.** Expected: all pass.
- [ ] **Step 5: Commit** `feat(ratelimit): sign-in, two-factor, forgot, reset, invite, setup and password limits`.

### Task 4: AI calls, webhooks and WebSocket connects

**Files:**
- Modify: `backend/app/memory/router.py` (`POST /api/memory/ask`), `backend/app/search/router.py` (`GET /api/search` when `meaning=true`), `backend/app/kb/router.py` (`GET /api/kb/search`), `backend/app/ai/router.py` (`POST /api/admin/ai/jobs/{job}/test`), `backend/app/mcp_server/memory_tools.py` (`ask_memory`, `search_memory`), `backend/app/mcp_server/kb_tools.py` (`kb_search`), `backend/app/git/router.py` (`receive_webhook`), `backend/app/realtime/router.py` (`/api/ws`), `backend/app/runner/router.py` (runner socket)
- Create: `backend/app/ratelimit/deps.py`
- Test: `backend/tests/ratelimit/test_ai_webhook_ws.py`

**Interfaces:**
- Consumes: Task 2 `middleware.current_subject`, Task 1 store API.
- Produces: `deps.ai_limit` (FastAPI dependency; hits `ai_user` for `current_subject`), `async deps.check_ai() -> None` (same, raising `RateLimited`; MCP tools convert it to `ToolError("rate_limited")`).

Notes: grep the REST routers and MCP tools for any other request-time call into `app.ai` (chat or embeddings) and add it to the same list; background jobs are not limited. Webhooks: peek `api_ip` first (blocked → 429, no work); then verify the signature; valid → hit `webhook_connection` (connection id) → 429 if blocked; unsigned/forged/unknown connection → hit `api_ip`, then answer as today (401/404). WebSockets: hit `ws_connect` (credential subject from cookie or bearer, else `ip:<addr>`) before `accept()`; blocked → `await websocket.close(code=1008)` before accepting.

- [ ] **Step 1: Write the failing tests:**

```python
async def test_ai_calls_have_their_own_limit(member, monkeypatch): ...      # ai_per_user=2: 2× POST /api/memory/ask ok, 3rd 429; GET /api/projects still 200
async def test_meaning_search_counts_only_with_meaning(member): ...          # meaning=false never counts
async def test_mcp_ask_memory_is_limited(mcp_client): ...                    # 3rd call → tool error "rate_limited"
async def test_forged_webhooks_do_not_use_the_connection_budget(client, git_connection): ...
    # webhook_per_connection=2, api_per_ip high: 10 unsigned → 401; then 2 signed → 204; 3rd signed → 429
async def test_forged_webhooks_count_per_ip(client, git_connection): ...     # api_per_ip=3: 4th unsigned → 429
def test_ws_connects_are_limited(sync_client_signed_in): ...                  # ws_connect=2: 3rd connect is refused (WebSocketDisconnect code 1008)
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** per the notes.
- [ ] **Step 4: Run `tests/ratelimit tests/git tests/realtime tests/runner tests/mcp tests/memory tests/kb tests/search`.** Expected: all pass.
- [ ] **Step 5: Commit** `feat(ratelimit): AI, webhook and WebSocket connect limits`.

### Task 5: Admin status and the frontend message

**Files:**
- Modify: `backend/app/ratelimit/` (router `GET /api/admin/rate-limits` → `{"working": bool}`, admin only), `backend/app/main.py`, `frontend/src/lib/api.ts`, `frontend/src/lib/errors.ts`, `frontend/src/lib/api-types.ts` (regenerate: `npm run gen:api` against a running dev API), `frontend/src/app/(app)/admin/settings/page.tsx`
- Create: `backend/app/ratelimit/router.py`, `frontend/src/components/admin/RateLimitsAdmin.tsx`
- Test: `backend/tests/ratelimit/test_admin.py`, `frontend/src/lib/__tests__/errors.test.ts`, `frontend/src/components/admin/__tests__/RateLimitsAdmin.test.tsx`

**Interfaces:**
- Produces: `ApiError.retryAfter: number | null` (from body `retry_after`); `errorMessage` handles 429.

- [ ] **Step 1: Write the failing tests:**

```python
async def test_admin_sees_rate_limit_status(admin): assert (await admin.get("/api/admin/rate-limits")).json() == {"working": True}
async def test_status_says_off_when_valkey_is_down(admin, monkeypatch): ... == {"working": False}
async def test_members_cannot_see_it(member): assert (await member.get("/api/admin/rate-limits")).status_code == 403
```

```ts
it("says when to try again", () => {
  expect(errorMessage(new ApiError(429, "rate_limited", 840))).toBe("Too many attempts. Try again in 14 minutes.");
  expect(errorMessage(new ApiError(429, "rate_limited", 60))).toBe("Too many attempts. Try again in 1 minute.");
  expect(errorMessage(new ApiError(429, "rate_limited", 30))).toBe("Too many attempts. Try again in 30 seconds.");
  expect(errorMessage(new ApiError(429, "rate_limited", 1))).toBe("Too many attempts. Try again in 1 second.");
});
it("reads retry_after from a 429 body", async () => { /* api() with a mocked 429 → ApiError.retryAfter === 840 */ });
it("shows Working, or that limits are off", async () => { /* RateLimitsAdmin: {working:true} → "Working"; false → "Valkey is unreachable — limits are off" in text-pink */ });
```

- [ ] **Step 2: Run to verify they fail.** `uv run pytest tests/ratelimit/test_admin.py -q`; `cd frontend && npx vitest run src/lib/__tests__/errors.test.ts src/components/admin/__tests__/RateLimitsAdmin.test.tsx`.
- [ ] **Step 3: Implement.** `RateLimitsAdmin` mirrors `SearchAdmin` (section "Rate limits", no button) and sits next to it on the admin settings page. The `ApiError` constructor gains an optional third argument.
- [ ] **Step 4: Run the tests, then the full frontend suite, `npx tsc --noEmit` and `npm run lint`.** Expected: all pass, clean.
- [ ] **Step 5: Commit** `feat(ratelimit): admin status and "try again in" message`.

### Task 6: Production deploy, docs and the end-to-end test

**Files:**
- Modify: `deploy/docker-compose.yml`, `deploy/.env.example`, `docs/install.md`, `README.md`, `.superpowers/e2e.env` (local only, git-ignored)
- Create: `frontend/e2e/ratelimits.spec.ts`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Compose and env.** `valkey` service (image per Global Constraints, `restart: unless-stopped`, `command: ["valkey-server", "--requirepass", "${VALKEY_PASSWORD:?set VALKEY_PASSWORD in .env}", "--save", "", "--appendonly", "no"]`, healthcheck `valkey-cli -a "$$VALKEY_PASSWORD" ping` with `VALKEY_PASSWORD` in its environment, no ports, no volume). Backend: `VALKEY_URL: valkey://:${VALKEY_PASSWORD}@valkey:6379/0`, `CLIENT_IP_HEADER: ${CLIENT_IP_HEADER:-}`, and each `RATE_LIMIT_*` passed through with its default (`${RATE_LIMIT_LOGIN_PER_IP:-30}` …); `depends_on: valkey: condition: service_started`. `.env.example` gains `VALKEY_PASSWORD` (with the `openssl rand -hex 32` hint) and a commented block of the limits and `CLIENT_IP_HEADER`.
- [ ] **Step 2: Docs.** `docs/install.md`: env table rows for `VALKEY_PASSWORD`, `CLIENT_IP_HEADER` (with the forgery warning from the spec) and the `RATE_LIMIT_*` settings; services count +1 (`valkey`); upgrade note "add `VALKEY_PASSWORD` to `.env` before upgrading"; troubleshooting entry for "Valkey is unreachable — limits are off". README: e2e env needs `VALKEY_PASSWORD` and `CLIENT_IP_HEADER=X-Real-IP`, and a "Rate limits end-to-end test" section.
- [ ] **Step 3: Write the e2e test** `frontend/e2e/ratelimits.spec.ts`. It uses its own client address through `CLIENT_IP_HEADER=X-Real-IP` (a browser context with `extraHTTPHeaders: {"X-Real-IP": "203.0.113.77"}`) so the other specs on the stack are never limited: 30 wrong-password `POST /api/auth/login` for `nobody@acme.io` → 401 each; the 31st → 429 with `retry_after` > 0; then the `/login` page in that context, a wrong password submitted → the text `Too many attempts. Try again in 15 minutes.` (or 14, allow `/Try again in 1[45] minutes\./`); a context without the header still signs in as the admin. Add `VALKEY_PASSWORD` and `CLIENT_IP_HEADER=X-Real-IP` to `.superpowers/e2e.env`.
- [ ] **Step 4: Run it on a fresh stack, then the whole e2e suite.** `MSYS_NO_PATHCONV=1 docker compose -p megoo-e2e -f deploy/docker-compose.yml --env-file .superpowers/e2e.env up -d --build --wait`, then `cd frontend && npx playwright test e2e/ratelimits.spec.ts`, then `down -v`, `up` again and `npx playwright test`. Expected: all pass. Tear the stack down.
- [ ] **Step 5: Commit** `feat(deploy): Valkey service, rate-limit settings, docs and e2e test`.
