# Valkey and rate limits — design

Date: 2026-10-28. Status: approved in conversation, pending the owner's read of this document.

## Why

MegooColab has no limit on how often anyone can call it. Someone can try passwords from many addresses, guess
two-factor codes, flood a person's inbox with password-reset emails, or run up the organization's AI bill. The owner
also expects to run MegooColab in a high-availability setup later, with several backends and frontends. Limits counted
in one backend's memory would then not hold, so the counters live in a shared store: Valkey (the open-source Redis
fork).

This is project 1 of 2. Project 2, high availability (several backends and frontends, cross-backend runner routing,
shared uploads, one migration at a time, shared periodic timers, load balancing), is a separate design that builds on
the Valkey this project adds. Background jobs stay on the existing PostgreSQL queue; Celery is out (owner's decision:
it would lose jobs queued in the same transaction as the change, and the backend is async).

## Goals

- Valkey is a **required** service in every deployment (production compose, dev compose, CI, the e2e stack), like
  Meilisearch.
- Rate limits on the abuse-prone and costly parts of the API, counted in Valkey so they hold across backends.
- A person who hits a limit sees when they can try again.
- Every limit has a default and can be changed in `.env`.

## Non-goals

- High availability itself (project 2).
- Caching. Valkey is not used as a cache in this project.
- Moving the existing per-account sign-in lockout out of PostgreSQL (see "Sign-in" below).
- Limits on the browser's static assets (the frontend), the health check or the WebSocket messages after connect.
- A UI to edit the limits. They are `.env` settings.

## Anti-goals

- A limit that real work trips over. The general API limit must be invisible in normal use, including a coding agent
  working through MCP.
- A Valkey outage that locks everyone out. When Valkey is unreachable, requests are allowed (fail open) and the outage
  is logged and visible to admins (see "When Valkey is down").
- Per-IP limits that lump every visitor together because the backend sees a proxy's address (see "Client address").

## The limits (owner-approved defaults)

| What | Counted per | Default | `.env` name (builder may adjust the names; keep one per number) |
|---|---|---|---|
| Failed sign-ins | client IP | 30 per 15 min | `RATE_LIMIT_LOGIN_PER_IP` |
| Wrong two-factor codes after a correct password (at sign-in), and on enable/disable two-factor | account | 5 per 15 min | `RATE_LIMIT_TOTP_PER_ACCOUNT` |
| Forgot-password emails | email address | 3 per hour | `RATE_LIMIT_FORGOT_PER_EMAIL` |
| Forgot-password requests | client IP | 10 per hour | `RATE_LIMIT_FORGOT_PER_IP` |
| Failed reset password, accept invite, first-run setup (bad or expired token, refused setup) | client IP | 10 per hour each | `RATE_LIMIT_TOKEN_PAGES_PER_IP` |
| Change password (signed in) | user | 5 per 15 min | `RATE_LIMIT_CHANGE_PASSWORD_PER_USER` |
| All other API calls, signed in | browser session: the user; a personal access token or an agent run token: that token | 600 per minute | `RATE_LIMIT_API_PER_USER` |
| All other API calls, not signed in | client IP | 120 per minute | `RATE_LIMIT_API_PER_IP` |
| Calls that make the server call an AI provider while the person waits | as above (user for a session, else the token) | 30 per minute | `RATE_LIMIT_AI_PER_USER` |
| Git webhook deliveries with a valid signature | git connection | 120 per minute | `RATE_LIMIT_WEBHOOK_PER_CONNECTION` |
| WebSocket connects (live updates, runner) — *my addition* | user, else client IP | 30 per minute | `RATE_LIMIT_WS_CONNECT` |

The AI group covers every endpoint that calls a chat or embeddings provider during the request: "ask the memory"
(`POST /api/memory/ask`), the results page's "Also match by meaning" (`GET /api/search` with the meaning switch on),
Knowledge Base semantic search, testing an AI provider (`POST /api/ai/jobs/{job}/test`), and the MCP tools that do the
same (`ask_memory`, `search_memory`, semantic KB search). The builder enumerates the full list from the code; an AI
call made by a background job is not limited here. An AI call counts against both the AI limit and the general one.

Webhooks (*my call*): the signature is checked first, then a valid delivery counts against its connection and is
exempt from the per-IP limit (a git host sends from few addresses). An unsigned or forged delivery, or one for an
unknown connection, counts against the per-IP limit for anonymous calls. Checking the signature before counting is
cheap and keeps a forged flood from using up a real connection's budget.

### Sign-in

The per-account lockout already exists in PostgreSQL (`app/auth/service.py`: 10 failed sign-ins in 15 minutes lock the
account for 15 minutes, raced-safe with a row lock, audited as `auth.locked`, answered with 423). It stays as it is:
it is durable and already counts across backends. This project adds the per-IP sign-in limit and the stricter
two-factor-code limit beside it. A wrong two-factor code still counts toward the account lockout too.

*My calls*, so that guessing someone's email is not enough to block them:
- **Only failures count** for the sign-in, reset, invite and setup limits: a wrong password, a bad or expired token, a
  refused setup. A successful request never uses up the budget, so an office of 40 people behind one address signing
  in on Monday morning, or an admin onboarding a whole team, never hits it. The counter is checked before the work (a
  blocked address gets 429 straight away) and added to only after the endpoint fails. Forgot-password counts every
  request, because each one may send an email.
- **A wrong two-factor code counts toward the 5-code limit only when the password was right.** Without the password,
  nobody can use up someone's code attempts. Once the limit is reached, that account's code checks are refused with
  429 until the window ends, even with the right code. The existing 423 `locked` takes precedence when both apply.

## When a limit is hit

- The response is **429** with detail `rate_limited`, a `Retry-After` header (seconds) and the same number in the body
  (`retry_after`), so the frontend can say it without parsing headers.
- The frontend shows "Too many attempts. Try again in N minutes" (or "in N seconds" under a minute) wherever an API
  error is shown today, and on the sign-in, forgot, reset, invite and setup pages in their own error spot.
- *My call on the frequency:* the audit log records a block once per counter per window (action `rate_limit.blocked`, with the limit's name and
  the IP or user), not on every rejected request.
- The check runs before the endpoint's work; a rejected request does no work. The failures-only limits add to
  their counter after the endpoint fails (see "Sign-in").

## Client address

Per-IP limits need each visitor's real address. Today uvicorn runs with `--proxy-headers --forwarded-allow-ips *`
behind Caddy, so the backend sees Caddy's `X-Forwarded-For`. When MegooColab sits behind another proxy (a Cloudflare
tunnel, a load balancer), every visitor would arrive with that proxy's address.

- New setting `CLIENT_IP_HEADER` (default empty: use the address uvicorn resolves, as today). Set to a header name such
  as `CF-Connecting-IP`, the backend reads the client address from that header.
- `docs/install.md` warns: set it only when every request reaches MegooColab through that proxy, because anyone who
  can reach Caddy directly can forge the header.
- The address is normalised (IPv6 grouped by /64, so one machine cannot rotate through its own block). *My call.*
- *My call:* this project supports single-value headers (`CF-Connecting-IP`, `X-Real-IP`, `True-Client-IP`). Reading
  the right entry of an `X-Forwarded-For` chain behind a load balancer, with Caddy's `trusted_proxies`, belongs to
  project 2, which adds the load balancing.

## When Valkey is down

- Requests are **allowed** and each failed check logs a warning (rate-limited in the log itself, so an outage does not
  flood it).
- *My addition:* Admin → Settings shows a **Rate limits** status line next to the existing Search status: "Working" or "Valkey is
  unreachable — limits are off" (red). `GET /api/admin/rate-limits` returns it.
- The backend starts even when Valkey is down (compose `depends_on: condition: service_started`, as for Meilisearch).

## Deployment

- `deploy/docker-compose.yml`: a `valkey` service with a pinned image version, no persistence (counters can be lost on
  restart; persistence off), a required password `VALKEY_PASSWORD` in `.env` (`:?` like `MEILI_MASTER_KEY`), reachable
  only on the compose network. Backend gets `VALKEY_URL` built from it. The worker does not need it in this project.
- `deploy/docker-compose.dev.yml`: Valkey on `localhost:6379` with a fixed dev password; tests and `make dev` use it
  (the Makefile's dev keys gain it).
- CI (`.github/workflows/ci.yml`): a Valkey service for the backend tests.
- `.env.example`, `docs/install.md` (env table, services count, troubleshooting, upgrade note: add
  `VALKEY_PASSWORD` before upgrading), `README.md` (dev setup, the e2e env file needs `VALKEY_PASSWORD`).

## Builder's calls (marked as mine where I made them)

- Agent run tokens (*my call*): each run token has its own counter, like each personal access token, so several
  agents working in parallel do not share one budget with their owner's browser. The number of runs is already
  capped per agent (`max_concurrent_runs`), which bounds how far this multiplies.
- Python client: `valkey-py` (asyncio API, `valkey.asyncio`). *My call*; any maintained async client is fine.
- Counting: fixed windows with `INCR` and `EXPIRE` in one round trip, keyed by limit name, subject and window start.
  *My call*: simple, and an edge burst of up to twice the limit for one moment is acceptable for these numbers.
- Where checks live: a FastAPI dependency for the named limits and one middleware for the general per-user/per-IP
  limit. The builder decides the exact shape.
- Tests may run against the dev Valkey (like Meilisearch) with a key prefix per test run.
- An e2e test that hits the sign-in limit and sees the message is expected; how it resets between runs is the
  builder's call (a fresh stack already does).
