# Telegram Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A site admin sets one Telegram bot; each person links their own Telegram chat and picks, per notification
kind, whether it reaches them in Telegram, as a one-way message with an "Open in MegooColab" button.

**Architecture:** A new `app.telegram` package holds the data (bot settings on `OrgSettings`, a link per person, one-
time link codes), a replaceable HTTP client, the admin and personal endpoints, the `/start` handling, the
`notify.telegram` job and a long-poll loop that runs beside the worker's job loop under a Postgres advisory lock.
`notifications.notify` enqueues the job like push. The web app gets an Admin › Settings › Telegram tab and a Telegram
section and column on Settings › Notifications.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic, httpx, the Postgres job queue (`app/jobs`), Next.js + React Query,
Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-02-telegram-notifications-design.md`

## Global Constraints

- Branch `feat/telegram` off develop. Every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  No Prettier (≈120-column lines, match surrounding code).
- Migrations only against `megoo_migrate` (`DEV_DATABASE_URL=… megoo_migrate bash scripts/makemigration.sh`); name every
  FK, unique and check constraint explicitly; check `alembic downgrade -1 && alembic upgrade head` there.
- Backend tests `cd backend && uv run pytest <path> -q` (never two pytest runs at once); lint
  `uv run --with ruff ruff check <files>` (existing I001 import-order findings in untouched files are left alone).
  Web `cd frontend && npx vitest run <files>`, then `npx tsc --noEmit -p . && npx eslint <files>`.
- Tests never call Telegram: `app.telegram.client.get_client()` is replaced in tests.
- The bot token is stored with `app.core.crypto.encrypt`, never returned to the browser, never in logs, errors,
  job payloads or audit data.
- Telegram API base `https://api.telegram.org/bot<token>/<method>`; parse mode `HTML`; long-poll timeout 25 s.
- Copy, verbatim: bot replies `Connected to MegooColab as <name>.` / `This link has expired. Open MegooColab › Settings ›
  Notifications and press Connect Telegram again.` / `This bot only sends MegooColab notifications.`; button
  `Open in MegooColab`; admin errors `Telegram doesn't accept this token` (`telegram_token_refused`) and `Couldn't reach
  Telegram from the server` (`telegram_unreachable`); disabled boxes `Connect Telegram first`.
- Link codes: `secrets.token_urlsafe(24)` (32 characters; Telegram's start payload allows 64), valid 15 minutes, single use.
- First-link default: Telegram on for the kinds the person gets as push; if none, `needs_you` and `mentioned`; only
  when none of their kinds has Telegram on.
- Audit actions: `telegram.bot_set`, `telegram.bot_removed` (actor: admin, data `{bot_username}`), `telegram.linked`,
  `telegram.unlinked` (actor: the person, or none for an automatic unlink; data `{reason}` with reason one of
  `disconnected`, `blocked`, `chat_gone`, `moved`, `bot_changed`).

## Review Focus

1. Two taps on the same Start link (or a forwarded link): the second `/start <code>` must not relink or move the
   chat — it gets the expired reply (Task 3 `test_a_code_works_once`).
2. A title or body with `<`, `>` or `&` (code snippets in task titles): escaped for HTML parse mode, or Telegram
   refuses the whole message (Task 4 `test_message_escapes_html`).
3. The token leaking through an exception: an httpx error's message contains the URL, which contains the token
   (Task 1 `test_errors_never_carry_the_token`).
4. A deactivated person who is still linked: no Telegram message (Task 4 `test_no_message_to_a_deactivated_person`).
5. The bot removed and the same bot set again: links come back and the old offset is kept; a different bot clears
   them (Task 2 `test_same_bot_keeps_links_other_bot_clears_them`).

---

### Task 1: Data and the Telegram client

**Files:**
- Create: `backend/app/telegram/__init__.py`, `backend/app/telegram/models.py`, `backend/app/telegram/client.py`
- Modify: `backend/app/org/models.py` (bot columns), `backend/app/notifications/models.py` (`NotificationPref.telegram`,
  `DEFAULT_PREFS` 4-tuples), `backend/app/notifications/service.py` (`preferences` returns 4-tuples; callers unpack 4),
  `backend/app/notifications/router.py` (`_prefs_out` and PUT carry `telegram`), `backend/app/notifications/schemas.py`
  (`NotificationPrefIO.telegram: bool = False`), `backend/app/models.py` (import the telegram models)
- Create: the migration `<rev>_telegram.py`
- Test: `backend/tests/telegram/__init__.py`, `backend/tests/telegram/test_client.py`,
  `backend/tests/notifications/test_push_prefs.py` (extend)

**Interfaces:**
- Produces:
  - `OrgSettings.telegram_token_enc: str | None`, `telegram_bot_id: int | None` (BigInteger),
    `telegram_bot_username: str | None` (String(100)), `telegram_offset: int | None` (BigInteger).
  - `TelegramLink` (table `telegram_links`): `user_id` PK FK users ON DELETE CASCADE, `chat_id` BigInteger unique
    (`uq_telegram_links_chat_id`), `linked_at` timestamptz default now().
  - `TelegramLinkCode` (table `telegram_link_codes`): `code` String(64) PK, `user_id` FK users ON DELETE CASCADE,
    `expires_at` timestamptz.
  - `NotificationPref.telegram: bool` (default False, server_default false).
  - `client.py`: `class TelegramError(Exception)` with `status: int`, `description: str`, `retry_after: int | None`;
    `class TelegramClient(Protocol)` with `async get_me(token) -> dict`, `async send_message(token, chat_id: int,
    text: str, button_url: str | None) -> None`, `async get_updates(token, offset: int | None, timeout: int) ->
    list[dict]`; `HttpTelegramClient` (httpx, timeout = poll timeout + 10 s); `get_client() -> TelegramClient`
    returning the module-level `override` when set, else an `HttpTelegramClient`. Network failures raise
    `TelegramError(status=0, …)`. Telegram's `{"ok": false, "error_code", "description", "parameters":
    {"retry_after"}}` becomes `TelegramError`.

- [ ] **Step 1: Write the failing tests** (`test_client.py`, httpx `MockTransport` injected through an
  `HttpTelegramClient(transport=…)` parameter):
  - `test_send_message_posts_html_with_a_button` → request to `/bot123:ABC/sendMessage`, JSON `{chat_id, text,
    parse_mode: "HTML", disable_web_page_preview: true, reply_markup: {inline_keyboard: [[{text: "Open in MegooColab",
    url}]]}}`; without a button no `reply_markup`.
  - `test_telegram_errors_carry_status_and_retry_after` → `{"ok": false, "error_code": 429, "description": "Too Many
    Requests", "parameters": {"retry_after": 7}}` raises `TelegramError(status=429, retry_after=7)`.
  - `test_errors_never_carry_the_token` → a `ConnectError` from the transport raises `TelegramError(status=0)` whose
    `str()` and `description` do not contain `123:ABC`.
  - In `test_push_prefs.py`: `test_telegram_preference_defaults_off_and_saves` → GET prefs: every kind
    `telegram: false`; PUT `{kind: "mentioned", in_app: true, email: true, push: false, telegram: true}` → GET shows it.
- [ ] **Step 2: Run, expect FAIL** — `uv run pytest tests/telegram/test_client.py tests/notifications/test_push_prefs.py -q`
  → import error / KeyError `telegram`.
- [ ] **Step 3: Implement** the columns, models, client and the 4-tuple prefs (audit data of a prefs change gains
  `telegram`). Generate the migration against `megoo_migrate` (`"telegram"`), then downgrade/upgrade there.
- [ ] **Step 4: Run, expect PASS** — the same files plus `uv run pytest tests/notifications tests/core/test_migrations.py -q`.
- [ ] **Step 5: Commit** — `feat(telegram): bot, link and preference data; the Telegram client`

### Task 2: The admin sets and removes the bot

**Files:**
- Create: `backend/app/telegram/service.py` (bot part), `backend/app/telegram/router.py`, `backend/app/telegram/schemas.py`
- Modify: `backend/app/main.py` (include the router)
- Test: `backend/tests/telegram/conftest.py` (a `FakeTelegram` fixture: records calls, scripted `get_me` /
  `send_message` / `get_updates` results or errors, installed as `client.override`), `backend/tests/telegram/test_bot.py`

**Interfaces:**
- Consumes: Task 1 models and client.
- Produces:
  - `GET /api/admin/telegram` → `TelegramBotOut {bot_username: str | None}`; `PUT /api/admin/telegram {token: str}`
    (1–200 chars) → `TelegramBotOut`; `DELETE /api/admin/telegram` → 204. Admin only (`AdminUser`).
  - `async bot_token(db) -> str | None` (decrypted, None without a bot) in `service.py`, used by Tasks 3–5.
  - `async unlink(db, user_id, *, reason: str, actor_id: uuid.UUID | None) -> None` (deletes the link, audits
    `telegram.unlinked`), used by Tasks 3–4.
- PUT: `get_me` → on `TelegramError` with status 0 → 502 `telegram_unreachable`; any other error (401/404) → 422
  `telegram_token_refused`. When the bot id differs from the stored one: delete every `TelegramLink` (each unlink
  audited, reason `bot_changed`, no actor) and every `TelegramLinkCode`, and set `telegram_offset = None`. Store the
  token encrypted, the bot id and username; audit `telegram.bot_set`. DELETE clears the token only (id, username and
  offset stay, so the same bot restores links); audit `telegram.bot_removed`. `GET` answers None while no token is set.

- [ ] **Step 1: Write the failing tests** (`test_bot.py`):
  - `test_admin_sets_a_bot` → PUT with FakeTelegram `get_me` = `{id: 42, username: "megoo_bot"}` → 200
    `{bot_username: "megoo_bot"}`; the stored token decrypts to the sent token; GET returns the username; a member
    gets 403.
  - `test_refused_and_unreachable_tokens_are_not_saved` → `get_me` raising `TelegramError(401)` → 422
    `telegram_token_refused`; status 0 → 502 `telegram_unreachable`; GET still `{bot_username: null}`.
  - `test_same_bot_keeps_links_other_bot_clears_them` → set bot 42, add a `TelegramLink` and a code, offset 900;
    DELETE → GET null, link kept; PUT bot 42 again → link kept, offset 900; PUT bot 43 → no links, no codes, offset
    None, an audit row `telegram.unlinked` with `{reason: "bot_changed"}`.
  - `test_the_token_never_leaves_the_server` → GET body and the audit rows' data contain no token text.
- [ ] **Step 2: Run, expect FAIL** — `uv run pytest tests/telegram/test_bot.py -q` → 404s.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `feat(telegram): the admin sets the site's bot`

### Task 3: A person links their account; the bot answers /start

**Files:**
- Modify: `backend/app/telegram/service.py`, `backend/app/telegram/router.py`, `backend/app/telegram/schemas.py`
- Test: `backend/tests/telegram/test_link.py`

**Interfaces:**
- Consumes: Task 2 `bot_token`, `unlink`, the `FakeTelegram` fixture.
- Produces:
  - `GET /api/me/telegram` → `MyTelegramOut {available: bool, bot_username: str | None, linked: bool}`;
    `POST /api/me/telegram/link` → `{url: "https://t.me/<bot username>?start=<code>"}` (409 `telegram_not_set` without
    a bot); `DELETE /api/me/telegram` → 204 (`unlink`, reason `disconnected`, actor the person).
  - `async handle_update(db, token: str, update: dict) -> None` — used by Task 5's poller: acts only on a
    `message` from a `private` chat. Text `/start <code>`: a code that exists, has not expired and belongs to an
    active user → delete the code; if another user has this chat, `unlink` them (reason `moved`, no actor); upsert the
    link for the code's user (replacing their old chat); `apply_first_link_defaults`; audit `telegram.linked`; reply
    `Connected to MegooColab as <name>.`. `/start` with an unknown/expired/used code (or none) → the expired reply.
    Any other text → `This bot only sends MegooColab notifications.`. Replies go through `send_message` with no button;
    a failing reply is logged, never raised.
  - `async apply_first_link_defaults(db, user_id) -> None` (Global Constraints rule; writes `NotificationPref` rows,
    keeping each kind's in_app/email/push).

- [ ] **Step 1: Write the failing tests** (`test_link.py`; build updates as `{"update_id": n, "message": {"chat":
  {"id": 5001, "type": "private"}, "text": "/start <code>"}}`):
  - `test_connect_makes_a_start_link` → with a bot `megoo_bot`, POST link → url `https://t.me/megoo_bot?start=<code>`
    and a code row for the user expiring in 15 min (±1 min).
  - `test_start_links_the_chat_and_replies` → `handle_update` → link `{user, chat 5001}`, the code gone, FakeTelegram
    sent `Connected to MegooColab as Bea.` to 5001, GET `/api/me/telegram` → `linked: true`.
  - `test_a_code_works_once` → the same update again → no change, reply is the expired text.
  - `test_an_expired_code_is_refused` → code with `expires_at` in the past → no link, expired reply.
  - `test_a_chat_moves_to_the_new_person` → chat 5001 linked to Ann; Bea's code from chat 5001 → Bea linked, Ann
    unlinked, audit `{reason: "moved"}`.
  - `test_first_link_switches_telegram_on_like_push` → Bea has push on for `assigned` only → after linking,
    telegram on for `assigned` only; Cai with no push → `needs_you` and `mentioned`; Bea unlinks, turns telegram off for
    `assigned` and on for `mentioned`, links again → still only `mentioned`.
  - `test_other_messages_get_one_line` → text `hello` → reply `This bot only sends MegooColab notifications.`; a
    `group` chat message → no reply, no link.
  - `test_disconnect` → DELETE → no link, audit `{reason: "disconnected"}` with the person as actor.
  - `test_no_bot_no_link` → without a bot, POST link → 409 `telegram_not_set`; GET → `available: false`.
- [ ] **Step 2: Run, expect FAIL** — `uv run pytest tests/telegram/test_link.py -q`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS** — `uv run pytest tests/telegram -q`.
- [ ] **Step 5: Commit** — `feat(telegram): a person links their chat with a Start link`

### Task 4: Notifications go to Telegram

**Files:**
- Create: `backend/app/telegram/jobs.py` (`notify.telegram`), `backend/app/telegram/messages.py` (formatting, the
  button rule)
- Modify: `backend/app/notifications/service.py` (`notify` enqueues `notify.telegram`), `backend/app/worker.py`
  (`app.telegram.jobs` in `HANDLER_MODULES`)
- Test: `backend/tests/telegram/test_send.py`

**Interfaces:**
- Consumes: Tasks 1–3 (`bot_token`, `unlink`, `TelegramLink`, `TelegramError`, `get_client`).
- Produces:
  - `message_text(title: str, body: str, url_text: str | None) -> str` — `<b>{escaped title}</b>\n{escaped body}`,
    plus `\n{url_text}` when given (`html.escape`, quote=False).
  - `button_url(public_url: str, link: str) -> str | None` — the full URL (`public_url` without trailing `/` + link)
    when the scheme is `https` and the host has a dot, is not `localhost`, and is not a private, loopback, link-local
    or reserved IP address; else None.
  - Job payload `{"user_id", "title", "body", "link"}`; `notify` enqueues it per recipient whose `telegram` pref is on
    for the kind and who has a `TelegramLink`, only while a bot token is set.
- The job: no bot, no link, or the user not active → return. Send `message_text(title, body, None if button else
  full URL)` with the button. `TelegramError` handling: 403 → `unlink(reason="blocked")`; 400 whose description
  contains `chat not found` → `unlink(reason="chat_gone")`; 400 mentioning `button` or `url` (case-insensitive) while
  a button was sent → send once more without the button (URL as text); 429 → enqueue the same payload with
  `run_after = now + retry_after` (default 30 s) and return; status 0 or ≥ 500 → raise (the queue retries); any other
  → log a warning without the token and return.

- [ ] **Step 1: Write the failing tests** (`test_send.py`, settings `public_url` patched per test):
  - `test_mentioned_person_gets_a_telegram_message` → Bea linked, telegram on for `mentioned`; a comment mentioning
    her → one `notify.telegram` job; running it sends to her chat a text starting `<b>` with the title and the button
    `https://megoo.example.com/projects/PAY/board?task=PAY-1`.
  - `test_not_linked_or_off_means_no_job` → telegram off → no job; on but not linked → no job; no bot → no job.
  - `test_message_escapes_html` → title `Fix <script> & co` → text contains `Fix &lt;script&gt; &amp; co`.
  - `test_button_only_for_a_public_https_address` → `button_url` is None for `http://megoo.example.com`,
    `https://localhost:8080`, `https://megoo`, `https://192.168.1.5`, `https://10.0.0.1`, `https://127.0.0.1`; set for
    `https://megoo.example.com`; without a button the text ends with the full URL.
  - `test_a_refused_button_is_dropped_and_sent_again` → first send raises `TelegramError(400, "Bad Request: BUTTON_URL_INVALID")`
    → second send without a button succeeds.
  - `test_blocked_or_gone_chat_unlinks` → 403 → link gone, audit `{reason: "blocked"}`; 400 `chat not found` → link
    gone, `{reason: "chat_gone"}`.
  - `test_rate_limit_waits_and_server_errors_retry` → 429 retry_after 7 → a new queued job with `run_after` ≈ now+7 s,
    no exception; 502 → the handler raises.
  - `test_no_message_to_a_deactivated_person` → user deactivated after the job was queued → no send.
- [ ] **Step 2: Run, expect FAIL** — `uv run pytest tests/telegram/test_send.py -q`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS** — `uv run pytest tests/telegram tests/notifications -q`.
- [ ] **Step 5: Commit** — `feat(telegram): notifications reach linked people in Telegram`

### Task 5: The long-poll loop in the worker

**Files:**
- Create: `backend/app/telegram/poller.py`
- Modify: `backend/app/worker.py` (run `run_telegram_poller(stop)` beside `run_worker(stop)` with `asyncio.gather`)
- Test: `backend/tests/telegram/test_poller.py`

**Interfaces:**
- Consumes: Task 3 `handle_update`, Task 2 `bot_token`, Task 1 client.
- Produces:
  - `POLL_LOCK = 727_101` (the advisory lock key), `POLL_TIMEOUT = 25`, `IDLE_SECONDS = 30`.
  - `async poll_once(db) -> bool` — no bot → False. Else `get_updates(token, offset=org.telegram_offset, timeout=
    POLL_TIMEOUT)`; each update through `handle_update`, then `telegram_offset = update_id + 1`, committed after each
    update; True. A `TelegramError` 409 (another poller) or status 0 → log and return False.
  - `async run_telegram_poller(stop: asyncio.Event) -> None` — holds `pg_try_advisory_lock(POLL_LOCK)` on its own
    connection; without the lock, or after `poll_once` returns False, waits `IDLE_SECONDS` (or until `stop`) and tries
    again; stops when `stop` is set; an unexpected exception is logged and the loop goes on.

- [ ] **Step 1: Write the failing tests** (`test_poller.py`):
  - `test_poll_once_handles_updates_and_moves_the_offset` → FakeTelegram returns updates 10 and 11 → both handled
    (a link made by `/start <code>` in 10), offset stored 12; the next call asks with offset 12.
  - `test_no_bot_no_poll` → no token → False and no `get_updates` call.
  - `test_another_poller_is_left_alone` → `get_updates` raises `TelegramError(409)` → False, offset unchanged.
  - `test_only_one_poller_holds_the_lock` → while one connection holds `pg_try_advisory_lock(POLL_LOCK)`, a second
    `run_telegram_poller` run with `stop` set after 0.2 s makes no `get_updates` call.
- [ ] **Step 2: Run, expect FAIL** — `uv run pytest tests/telegram/test_poller.py -q`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS** — `uv run pytest tests/telegram tests/jobs -q`.
- [ ] **Step 5: Commit** — `feat(telegram): the worker listens for Start presses`

### Task 6: Admin › Settings › Telegram

**Files:**
- Create: `frontend/src/lib/telegram.ts`, `frontend/src/components/admin/TelegramForm.tsx`
- Modify: `frontend/src/app/(app)/admin/settings/page.tsx` (tab `{ id: "telegram", label: "Telegram" }` after Email),
  `frontend/src/lib/errors.ts` (`telegram_token_refused`, `telegram_unreachable`, `telegram_not_set` copy),
  `frontend/src/lib/api-types.ts` (`npm run gen:api`)
- Test: `frontend/src/components/admin/__tests__/TelegramForm.test.tsx`

**Interfaces:**
- Consumes: Task 2 endpoints.
- Produces (`lib/telegram.ts`): `telegramKeys = { all: ["telegram"], admin: ["telegram","admin"], mine: ["telegram","mine"] }`,
  `useAdminTelegram()`, `useMyTelegram(refetchInterval?: number | false)`.
- Form: with no bot — short steps ("1. In Telegram, open @BotFather and send /newbot. 2. Pick a name and a username.
  3. Paste the token it gives you here."), a password Input "Bot token" and Save (PUT). With a bot — "Connected to
  @<username>." and a Remove button behind a confirm ("Remove the bot? Telegram notifications stop for everyone.").
  Errors through `errorMessage` in an alert.

- [ ] **Step 1: Write the failing tests**: `saves a token and shows the bot` (PUT body `{token}` → "Connected to
  @megoo_bot."); `shows why a token was refused` (422 `telegram_token_refused` → "Telegram doesn't accept this token");
  `removes the bot after asking` (confirm → DELETE).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS** — `npx vitest run src/components/admin "src/app/(app)/admin"`, tsc, eslint.
- [ ] **Step 5: Commit** — `feat(telegram): Admin › Settings › Telegram`

### Task 7: Settings › Notifications — connect and choose

**Files:**
- Create: `frontend/src/components/notifications/TelegramConnect.tsx`
- Modify: `frontend/src/components/notifications/NotificationPrefs.tsx` (a Telegram column),
  `frontend/src/app/(app)/settings/notifications/page.tsx` (TelegramConnect after PushDevices; subtitle "Choose what
  reaches you in the app, by email, as push notifications and in Telegram. …"), `frontend/src/lib/notifications.ts`
  (the pref's `telegram` in `useSavePref` comparisons)
- Test: `frontend/src/components/notifications/__tests__/TelegramConnect.test.tsx`, `.../NotificationPrefs.test.tsx`
  (extend)

**Interfaces:**
- Consumes: Task 3 endpoints, Task 6 `useMyTelegram`, prefs `telegram`.
- TelegramConnect: hidden while `available` is false. Not linked: "Connect Telegram" → POST link → `window.open(url,
  "_blank", "noopener")`, then "Waiting for you to press Start in Telegram…" while `useMyTelegram(3000)` until
  `linked`; on linking, prefs are refetched (the first-link defaults changed them). Linked: "Connected to Telegram"
  and "Disconnect Telegram" (DELETE).
- NotificationPrefs: a "Telegram" column only while `available`; its checkboxes (`aria-label="Telegram: <kind>"`)
  disabled with `title="Connect Telegram first"` until `linked`.

- [ ] **Step 1: Write the failing tests**: `hidden without a bot`; `connect opens the Start link and waits`
  (window.open called with the url; after GET answers `linked: true` → "Connected to Telegram"); `disconnect`;
  in NotificationPrefs: `a Telegram column only with a bot, disabled until linked` and `ticking Telegram saves it`
  (PUT body has `telegram: true`).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS** — `npx vitest run`, tsc, eslint.
- [ ] **Step 5: Commit** — `feat(telegram): connect Telegram and choose what goes there`

### Task 8: Whole-system check

- [ ] **Step 1:** `cd backend && uv run pytest -q > <workspace>/pytest.txt 2>&1` → all passed.
- [ ] **Step 2:** the full e2e suite on the `megoo-e2e` stack (scratchpad `e2e-run-*.sh` pattern; never the owner's
  `megoocolab-*` containers) → all passed. The worker container must start with the poller (no bot: it idles).
- [ ] **Step 3:** if anything changed, commit — `test: …`.
