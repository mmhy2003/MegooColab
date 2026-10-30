# Web Push Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A third notification channel, web push: chosen per kind in Settings → Notifications and turned on per device, then sent by a worker job to every device of each recipient who ticked it.

**Architecture:**
- **Preferences:** `notification_prefs` gains a `push` column, off by default.
- **New `app/push` module:**
  - holds the device subscriptions and the server's VAPID keys (generated on first need, private key encrypted in org settings);
  - adds a `notify.push` job, one per device, that sends with `pywebpush` and cleans up dead devices.
- **Frontend:**
  - the service worker shows the push and opens its link on click;
  - Settings shows a device card (Turn on / Turn off, other devices) and a Push column.

**Tech Stack:** Python 3.12 (FastAPI, SQLAlchemy/Alembic, `pywebpush`, `cryptography`, pytest); Next 16 / React 19 / TanStack Query / vitest; plain-JS service worker.

**Spec:** `docs/superpowers/specs/2026-10-30-web-push-design.md`

## Global Constraints

- **Where the work goes:** a branch `feat/web-push` off `develop`, merged back into `develop`. No version bump, and no change under `runner/`.
- **Defaults:** push is off for every kind, for every user, existing ones included (`DEFAULT_PREFS` push `False`; the migration's server default is `false`).
- **When a push is sent:**
  - it goes after the commit, from the worker job `notify.push`, one job per subscription, with payload `{"subscription_id", "title", "body", "link"}`;
  - push follows exactly the recipients `notify()` already picks, and is independent of `in_app` and `email`.
- **Push service answers:**
  - `404`, `410` and `403` → delete the subscription;
  - any other `4xx` → log it and drop the message (the job succeeds);
  - `429`, `5xx` and network errors → raise, so the queue retries.
- **Message:** the payload is JSON `{"title", "body", "link"}`, with TTL `86400`. The service worker shows it with icon `/icons/icon-192.png`, `tag` = link and `data.link` = link. A click focuses an open MegooColab window and navigates it to the link, or opens one.
- **VAPID keys:**
  - stored on `org_settings`: `vapid_public_key` (base64url, uncompressed P-256 point) and `vapid_private_key_enc` (PEM, encrypted with `app.core.crypto.encrypt`);
  - if decryption fails, log a warning, generate a new pair and delete every subscription;
  - subject: `PUBLIC_URL` if it starts with `https://`, else `mailto:` + `smtp_from` if set, else `mailto:megoocolab@localhost`.
- **Subscriptions:**
  - an endpoint is unique;
  - registering an existing endpoint moves it to the current user and refreshes its keys and name;
  - a password reset and a deactivation delete all of that user's subscriptions;
  - sign-out deletes this device's subscription first.
- **Copy, verbatim:**
  - page subtitle: `Choose what reaches you in the app, by email and as push notifications. Email is sent only when an admin has set up SMTP.`
  - column `Push`, with checkbox labels `Push: {kind label}`.
  - card, by state:

    | State | Copy |
    | --- | --- |
    | Off | `Push is off on this device` / `Turn it on to get notifications here even when MegooColab is closed.` / button `Turn on` |
    | On | `Push is on for this device` / button `Turn off` |
    | Blocked | `Your browser blocks notifications from MegooColab. Allow them in this site's settings, then reload the page.` |
    | Unsupported | `This browser can't receive push notifications.` |
    | iOS, not installed | `On iPhone and iPad, add MegooColab to your Home Screen (Share → Add to Home Screen) and open it from there to turn on push.` |

  - device list heading `Other devices getting push`; each row `{name} · since {date}` with button `Remove`.
- **Device names** come from the request's `User-Agent`, as `{Browser} on {OS}`:
  - Browser: one of `Edge`, `Chrome`, `Firefox`, `Safari`, else `Browser`;
  - OS: one of `Windows`, `Android`, `iPhone`, `iPad`, `macOS`, `Linux`, else `this device`;
  - examples: `Chrome on Windows`, `Safari on iPhone`.
- **Working rules:**
  - Docker: only the `megoo-e2e` compose project and the dev containers;
  - migrations go against `megoo_migrate` only;
  - never run two pytest runs at once;
  - commit trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Before writing the `pywebpush` call, check its current API (`webpush(...)`, `WebPushException.response`) in its docs (Context7 if authorized, else PyPI/GitHub). The call is synchronous: run it with `asyncio.to_thread`.

## Review Focus

1. **A device shared between accounts.** Person A turns push on and signs out, then B signs in and turns it on: only B gets push there (Task 2 `test_register_moves_endpoint_to_new_user`, Task 5 sign-out test).
2. **A password reset.** Every device of that person stops getting push (Task 2 `test_password_reset_deletes_subscriptions`).
3. **One dead device among several.** The others still get the push, and a retry never resends to the ones that worked (Task 3: one job per subscription; `test_gone_device_is_deleted`).
4. **`SECRET_KEY` changed.** The keys regenerate and the old subscriptions go, with no crash on every notification (Task 2 `test_undecryptable_key_regenerates_and_clears_devices`).
5. **Push ticked while In app is off.** Push still goes out (Task 3 `test_push_independent_of_in_app`).

---

### Task 1: Push in the preferences

**Files:**
- Modify:
  - `backend/app/notifications/models.py`: `NotificationPref.push: Mapped[bool]` with server default false; `DEFAULT_PREFS: dict[Kind, tuple[bool, bool, bool]]`, push `False`;
  - `backend/app/notifications/schemas.py`: `NotificationPrefIO.push: bool = False`;
  - `backend/app/notifications/router.py`: `_prefs_out`, `put_preferences` and the audit data carry `push`;
  - `backend/app/notifications/service.py`: `preferences()` returns triples, and `notify()` unpacks `in_app, email, push`, with `push` unused until Task 3.
- Create: the migration `<rev>_notification_push.py` and `backend/tests/notifications/test_push_prefs.py`.

**Interfaces:**
- Produces: `preferences(db, user_ids, kind) -> dict[uuid.UUID, tuple[bool, bool, bool]]` (in_app, email, push).

- [ ] **Step 1: Write the failing tests:**
  - `test_push_defaults_off`: `GET /api/me/notification-preferences` → every item has `push is False`.
  - `test_push_saved_per_kind`: PUT `[{"kind": "mentioned", "in_app": true, "email": false, "push": true}]` → returned and re-read `mentioned.push is True`; other kinds stay `False`.
  - `test_put_without_push_keeps_push_off`: PUT an item with no `push` field → 200, and `push is False`, since the field defaults to false.
- [ ] **Step 2: Run** `cd backend && uv run pytest tests/notifications/test_push_prefs.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement.** Generate the migration against `megoo_migrate` (`alembic revision --autogenerate -m "notification push"`; add `server_default=sa.false()`), then check `downgrade -1` / `upgrade head`.
- [ ] **Step 4: Run** that file, then `uv run pytest tests/notifications tests/core/test_migrations.py -q -p no:cacheprovider`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(notifications): a push preference per kind`.

### Task 2: Devices and keys

**Files:**
- Create:
  - `backend/app/push/__init__.py`;
  - `backend/app/push/models.py`: `PushSubscription(id, user_id FK users cascade, endpoint String(1000) unique, p256dh String(200), auth String(100), name String(100), created_at, last_used_at nullable)`;
  - `backend/app/push/keys.py`, `backend/app/push/service.py`, `backend/app/push/router.py`, `backend/app/push/schemas.py`;
  - the migration `<rev>_push_subscriptions.py`;
  - `backend/tests/push/__init__.py`, `test_subscriptions.py`, `test_keys.py`.
- Modify:
  - `backend/app/org/models.py`: `vapid_public_key: str | None`, `vapid_private_key_enc: str | None`;
  - `backend/app/main.py`: include the router;
  - `backend/app/auth/router.py` (`reset_password`) and `backend/app/users/router.py` (`deactivate_user`): call `delete_user_subscriptions`;
  - `backend/pyproject.toml` (+`uv.lock`): add `pywebpush`.

**Interfaces:**
- Produces (`app/push/keys.py`):
  - `@dataclass(frozen=True) class VapidKeys: public_key: str; private_key_pem: str; subject: str`;
  - `async def vapid_keys(db) -> VapidKeys`: generates and stores the pair on first call, locking the org row `FOR UPDATE` so concurrent first calls agree. If the private key won't decrypt, it regenerates and deletes all `PushSubscription` rows;
  - `def vapid_subject(public_url: str, smtp_from: str | None) -> str`.
- Produces (`app/push/service.py`):
  - `def device_name(user_agent: str | None) -> str` (Global Constraints);
  - `async def delete_user_subscriptions(db, user_id) -> None`.
- Produces (routes; cookie session only, mounted like `tokens_router` with `dependencies=[Depends(current_session)]`):
  - `GET /api/push/key` → `{"public_key": str}`;
  - `GET /api/push/subscriptions` → `[PushSubscriptionOut{id, endpoint, name, created_at}]`, the user's own, newest first;
  - `POST /api/push/subscriptions` `{endpoint, keys: {p256dh, auth}}` → 201 `PushSubscriptionOut`. The endpoint must be `https://`, else 422 `invalid_push_endpoint`;
  - `DELETE /api/push/subscriptions/{id}` → 204, or 404 `push_subscription_not_found` when it isn't the user's.

- [ ] **Step 1: Write the failing tests.**
  - `test_keys.py`:
    - `test_key_generated_once`: two calls → the same public key, 87 base64url characters (65 bytes);
    - `test_undecryptable_key_regenerates_and_clears_devices`: corrupt `vapid_private_key_enc`, with one subscription present → a new public key, and 0 subscriptions;
    - `test_subject`: `https://megoo.example.com` → itself; `http://localhost:8080` with `smtp_from="ops@x.io"` → `mailto:ops@x.io`; with neither → `mailto:megoocolab@localhost`.
  - `test_subscriptions.py`:
    - `test_register_list_delete`: POST with UA `Mozilla/5.0 (Windows NT 10.0; Win64; x64) … Chrome/130.0 Safari/537.36` → `name == "Chrome on Windows"`; GET lists it; DELETE → 204, then the list is empty;
    - `test_register_moves_endpoint_to_new_user`: A registers endpoint E; B registers E → A's list is empty and B's has E, with the new keys;
    - `test_cannot_delete_someone_elses`: → 404;
    - `test_rejects_non_https_endpoint`: → 422;
    - `test_bearer_token_cannot_register`: a request with an MCP token → 401 or 403, as the existing cookie-only routes answer;
    - `test_password_reset_deletes_subscriptions`: two devices, then the reset flow (`/api/auth/forgot` mail token → `/api/auth/reset`) → none left;
    - `test_deactivation_deletes_subscriptions`;
    - `test_device_names`, parametrized, at least:

      | User agent | Name |
      | --- | --- |
      | iPhone Safari | `Safari on iPhone` |
      | Android Chrome | `Chrome on Android` |
      | Mac Firefox | `Firefox on macOS` |
      | Edge (`Edg/`) | `Edge on Windows` |
      | `None` | `Browser on this device` |
- [ ] **Step 2: Run** `cd backend && uv run pytest tests/push -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Generate keys with `cryptography`: `ec.generate_private_key(ec.SECP256R1())`.
  - The public key is `X962` `UncompressedPoint` bytes, base64url with no padding.
  - The private key is PKCS8 PEM, unencrypted, then `encrypt()`.
  - Generate the migration against `megoo_migrate`.
- [ ] **Step 4: Run** the same command, then `uv run pytest tests/auth tests/users tests/core/test_migrations.py -q -p no:cacheprovider`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(push): device subscriptions and the server's push keys`.

### Task 3: Sending

**Files:**
- Create: `backend/app/push/jobs.py` and `backend/tests/push/test_send.py`.
- Modify:
  - `backend/app/notifications/service.py`: in `notify()`, after the in-app and email handling, for each recipient with `push` ticked, enqueue `notify.push` for each of their subscriptions;
  - `backend/app/worker.py`: add `"app.push.jobs"` to `HANDLER_MODULES`.

**Interfaces:**
- Consumes: Task 1's `preferences` triple; Task 2's `PushSubscription`, `vapid_keys`.
- Produces (`app/push/jobs.py`):
  - `async def deliver(sub: PushSubscription, payload: str, keys: VapidKeys) -> int`: returns the push service's HTTP status. It is the only place `pywebpush` is called, through `asyncio.to_thread`. A network error raises.
  - `@queue.register("notify.push") async def send_push(db, payload: dict) -> None`:
    - loads the subscription (gone → return) and its user (not active → return);
    - calls `deliver` with `json.dumps({"title", "body", "link"})`;
    - acts on the status per Global Constraints;
    - on success (`2xx`), sets `last_used_at`.

- [ ] **Step 1: Write the failing tests.** `deliver` is monkeypatched to record its calls and return a chosen status. Job rows are read the way `tests/notifications/test_core.py:135` reads `notify.email` jobs.
  - `test_no_push_when_unticked`: a user with one subscription and push off for `mentioned` → `notify(... Kind.mentioned ...)` enqueues no `notify.push`.
  - `test_one_job_per_device`: push ticked, two subscriptions → two jobs, each with its `subscription_id`, the title, body and link.
  - `test_push_independent_of_in_app`: `in_app=False, email=False, push=True` → no in-app row, one push job.
  - `test_job_sends_payload`: run `send_push` → `deliver` gets `{"title": …, "body": …, "link": …}` as JSON; `last_used_at` is set.
  - `test_gone_device_is_deleted`, parametrized over 404, 410 and 403 → the subscription is deleted and nothing is raised.
  - `test_other_client_error_is_dropped`: 400 → the subscription is kept, nothing is raised.
  - `test_server_error_retries`, over 500 and 429 → raises.
  - `test_inactive_user_gets_nothing`: deactivated → `deliver` is not called.
- [ ] **Step 2: Run** `cd backend && uv run pytest tests/push/test_send.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/push tests/notifications -q -p no:cacheprovider`, then the whole backend suite in the background, reading its tail. Expected: PASS.
- [ ] **Step 5: Commit** `feat(push): send notifications as web push`.

### Task 4: The service worker

**Files:**
- Modify: `frontend/public/sw.js`, adding `push` and `notificationclick` listeners.
- Create: `frontend/src/app/__tests__/sw.test.ts`.

**Interfaces:**
- `sw.js` is loaded in the test with `node:vm`, in a sandbox providing:
  - `self` with `addEventListener` recording the handlers, `registration.showNotification` as a spy, `clients.matchAll` / `clients.openWindow` as spies, and `location.origin`;
  - `caches`.

  The worker's own install/fetch code must still load in that sandbox.

- [ ] **Step 1: Write the failing tests:**
  - `shows the push`: a push event with `data.json()` = `{title:"PAY-1: t", body:"b", link:"/projects/PAY/board?task=PAY-1"}` → `showNotification("PAY-1: t", {body:"b", icon:"/icons/icon-192.png", tag:"/projects/PAY/board?task=PAY-1", data:{link:"/projects/PAY/board?task=PAY-1"}})`, passed to `event.waitUntil`.
  - `focuses an open window on click`: `matchAll` returns a client with `url` on the origin → `client.navigate(origin + link)` and `client.focus()` are called; `openWindow` is not; `notification.close()` is called.
  - `opens a window when none is open`: → `openWindow(link)`.
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/app/__tests__/sw.test.ts`. Expected: FAIL.
- [ ] **Step 3: Implement** the two listeners.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(pwa): show push notifications and open their link`.

### Task 5: Settings and sign-out

**Files:**
- Create:
  - `frontend/src/lib/push.ts`;
  - `frontend/src/components/notifications/PushDevices.tsx`;
  - `frontend/src/components/notifications/__tests__/PushDevices.test.tsx`, `NotificationPrefs.test.tsx` (or extend the existing file if there is one).
- Modify:
  - `frontend/src/lib/api-types.ts` (`npm run gen:api`);
  - `frontend/src/lib/errors.ts`: `invalid_push_endpoint`: `This browser gave an address MegooColab can't send to.` and `push_subscription_not_found`: `That device was already removed.`;
  - `frontend/src/components/notifications/NotificationPrefs.tsx`: the Push column, with `push` in the unsaved comparison;
  - `frontend/src/app/(app)/settings/notifications/page.tsx`: the subtitle, and `<PushDevices />` above `<NotificationPrefs />`;
  - `frontend/src/components/shell/Header.tsx`: sign-out calls `await forgetThisDevice()` (errors swallowed) before `/api/auth/logout`.

**Interfaces:**
- Produces (`lib/push.ts`):
  - `type PushState = "unsupported" | "ios-install" | "blocked" | "off" | "on"`;
  - `function pushSupport(): "supported" | "unsupported" | "ios-install"`:
    - `"ios-install"` on iPhone/iPad when not `navigator.standalone` and not `matchMedia("(display-mode: standalone)")`;
    - `"unsupported"` without `serviceWorker`, `PushManager` or `Notification`.
  - `async function thisDeviceEndpoint(): Promise<string | null>`;
  - `async function turnOnPush(): Promise<void>`: `Notification.requestPermission()`, then `navigator.serviceWorker.ready`, then `pushManager.subscribe({ userVisibleOnly: true, applicationServerKey })` with the key from `/api/push/key`, then POST.
  - `async function turnOffPush(id: string): Promise<void>`: unsubscribe locally, then DELETE.
  - `async function forgetThisDevice(): Promise<void>`: finds this device's row by endpoint, then DELETEs it and unsubscribes.
- `PushDevices`:
  - computes its state from `pushSupport()`, `Notification.permission` and whether this device's endpoint is in `GET /api/push/subscriptions` (query key `["push", "subscriptions"]`);
  - lists the other rows, with Remove → DELETE.

- [ ] **Step 1: Write the failing tests.** `PushDevices.test.tsx` mocks `fetch`, and `navigator` / `Notification` / `PushManager` per test:
  - each of the five states shows its copy, verbatim from Global Constraints;
  - `Turn on` calls `requestPermission`, subscribes with the server key and POSTs the subscription; a denied permission shows the Blocked copy;
  - the other devices are listed as `Chrome on Windows · since …` with `Remove` → a DELETE to `/api/push/subscriptions/{id}`;
  - the permission prompt never appears on load (`requestPermission` is not called before a click).

  `NotificationPrefs`:
  - shows a `Push` column, with every box unticked by default;
  - ticking `Push: Mentioned` PUTs `{kind:"mentioned", in_app, email, push:true}`.

  Header:
  - sign-out calls `DELETE /api/push/subscriptions/{id}` for this device before `/api/auth/logout`.
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/components/notifications src/components/shell`. Expected: FAIL.
- [ ] **Step 3: Implement**, after `npm run gen:api`.
- [ ] **Step 4: Run** `cd frontend && npx vitest run && npm run lint && npx tsc --noEmit`. Expected: all pass.
- [ ] **Step 5: Commit** `feat(web): turn on push per device and choose it per kind`.

### Task 6: Docs and the whole branch

**Files:**
- Modify: `docs/install.md`, adding a short "Push notifications" note:
  - each person turns push on per device under Settings → Notifications;
  - it needs HTTPS and outbound access to the browsers' push services;
  - on iPhone, only from the Home Screen app;
  - the server makes its own keys, and changing `SECRET_KEY` makes everyone turn push on again.

- [ ] **Step 1: Edit** the docs.
- [ ] **Step 2: Run** the e2e suite on a fresh `megoo-e2e` stack, built with `-f deploy/docker-compose.build.yml`. Expected: all pass (the notification specs still see their table).
- [ ] **Step 3: Run** every suite on the branch tip: backend pytest, frontend vitest, lint and tsc. Expected: all pass.
- [ ] **Step 4: Commit** `docs: web push notifications`.
