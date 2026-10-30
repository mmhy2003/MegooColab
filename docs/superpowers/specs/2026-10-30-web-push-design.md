# Web push notifications — design

Date: 2026-10-30. Status: draft for approval.

## Why

MegooColab already notifies people:

- **Five kinds:**
  - `needs_you`
  - `assigned`
  - `mentioned`
  - `agent_offline`
  - `question_waiting`
- **Two channels**, each switchable per kind in Settings → Notifications:
  - **in app**, the bell;
  - **email**, sent by a worker job and only when SMTP is set up.

These only reach you when you look at the app or your inbox. The owner wants notifications that arrive on their phone or computer as **web push**, even when MegooColab is closed, as a third channel chosen per kind like the other two.

MegooColab is already an installable PWA: it has `frontend/public/sw.js`, which `ServiceWorker.tsx` registers in production builds. That service worker doesn't handle push yet.

## Goals

1. **A third channel, push**, chosen per notification kind in Settings → Notifications as a **Push** column next to In app and Email (decided by the owner).
2. **Push starts unticked for every kind** (decided by the owner), for everyone, including existing users. People pick what they want. *Claude's call:* the setting is independent of In app and Email, as Email is independent of In app today.
3. **A device card above the table** (mockup option A, decided by the owner):
   - **This device:** "Push is off on this device" with a **Turn on** button, or "Push is on for this device" with **Turn off**. Turn on asks the browser's permission and registers the device.
   - **Other devices getting push:** each one has a readable name (e.g. "Chrome on Windows", "Safari on iPhone"), the date it was added, and **Remove**.
   - **Other states:**
     - if the browser blocked permission, the card says so and how to allow it again;
     - if the browser has no push support, the card says push isn't available there;
     - **iPhone/iPad not installed:** when it isn't running as an installed app, the card says to add MegooColab to the Home Screen first (iOS allows push only for installed web apps).
4. **What arrives:** the notification's own title and body, the MegooColab icon, and a tap that opens or focuses MegooColab at the notification's `link`. *Claude's call:* it is shown even when a MegooColab tab is open. Browsers expect every push to be displayed, and quietly dropping it is unreliable.
5. **When it is sent:**
   - **Who:** every recipient who gets a notification (the existing `notify()` rules decide who) and has Push ticked for that kind.
   - **Where:** to every device they registered.
   - **When:** after the commit, from a worker job, like email.
   - It's independent of whether an in-app row was created. Push ticked with In app unticked still pushes.
6. **No admin setup.** *Claude's call:* the server generates its VAPID key pair once, on first need, and stores it the way it stores other server secrets (encrypted with `SECRET_KEY`). The VAPID contact is `PUBLIC_URL`.
7. **Devices clean themselves up** (*Claude's call*). What the device's push service answers decides what happens:
   - **404/410** (the app was uninstalled, data cleared or permission revoked) and **403** (the key no longer matches): the device is deleted.
   - **Other 4xx:** logged and dropped, with no retry.
   - **Network errors, 5xx and 429:** retried by the job queue.
   - None of these blocks anything else.
8. **A device belongs to the person, not to one sign-in** (*Claude's call*), so push keeps arriving even if they don't open MegooColab for weeks.
   - **Signing out** on a device removes that device.
   - **A password reset** (account recovery) and **deactivation** remove all of that person's devices, so whoever had the account stops getting its notifications.
   - **A session expiring** and **changing the password** (the person knows it) keep devices.

## Non-goals

- Push for anything that isn't already a notification. The kinds stay the five above.
- Native mobile apps, or Firebase/APNs credentials of our own. Standard Web Push (VAPID) only.
- Grouping or digests, quiet hours, sounds, or action buttons on the notification.
- An admin switch to disable push server-wide. *Claude's call:* not needed for now, because nothing is sent unless a person turns it on.
- Hiding push while the app is open (see goal 4).

## Anti-goals (a failure even if it works)

- Push arriving for a kind the person didn't tick, or for a project or task they can no longer see.
- A permission prompt that pops up by itself. The browser asks only after **Turn on** is clicked.
- A failing push service (offline server, expired device) slowing or breaking the action that caused the notification, or the email and in-app delivery.
- Notification text leaking to someone else's device: a device belongs to the user who registered it, while signed in.

## How it works

### Data

- `notification_prefs.push: bool`, default false. Existing rows and the defaults (`DEFAULT_PREFS`) get push off. The prefs API (`GET` and `PUT /api/me/notification-preferences`) carries `push` alongside `in_app` and `email`.
- `push_subscriptions`:
  - `id`;
  - `user_id` (FK users, cascade);
  - `endpoint` (unique);
  - `p256dh`, `auth` (the browser's keys);
  - `name` (the readable device name, from the user agent at registration);
  - `created_at`, `last_used_at`.

  Registering an endpoint that already exists moves it to the current user and refreshes its keys. A shared computer switching accounts then doesn't push the old user's notifications.
- **VAPID key pair:** stored once in org settings, with the private key encrypted by `core/crypto.py` like `smtp_password_enc`.
  - *Claude's call:* if it can't be decrypted (`SECRET_KEY` changed), the server logs a warning, generates a new pair and deletes every subscription, since they're tied to the old key and can't work. Devices then show push as off, and people turn it on again.
  - VAPID contact: `PUBLIC_URL` when it is `https:`, otherwise `mailto:` the SMTP from-address if set, otherwise `mailto:megoocolab@localhost`. Push services expect `https:` or `mailto:`.

### API (all for the signed-in user, cookie session only)

- `GET /api/push/key`: the VAPID public key, which the browser needs to subscribe.
- `POST /api/push/subscriptions` `{endpoint, keys: {p256dh, auth}}` registers this device and returns it.
- `GET /api/push/subscriptions` lists the user's devices, so the card can mark which is "this device" by comparing endpoints.
- `DELETE /api/push/subscriptions/{id}` removes one.
- **Sign-out:** the frontend unsubscribes this device and deletes its row first. Password reset (`reset_password`) and deactivation delete all of the user's subscriptions server-side (goal 8).

### Sending

- **Enqueueing:** in `notify()`, for each recipient with `push` ticked, enqueue one `notify.push` job **per subscription** (*Claude's call*), `{subscription_id, title, body, link}`. A retry then resends only to the device that failed.
- **Repeats:** push goes to the same recipients `notify()` already picks. That includes its 10-minute "unread repeat about the same task" filter: when someone has In app off, no rows exist to filter on. *Claude's call:* the notification `tag` (its link) makes a repeat replace the earlier one on the device instead of piling up, so no extra filter is added.
- **Sending:** the `pywebpush` library (*Claude's call*), TTL about a day.
- The payload is JSON `{title, body, link}`, encrypted per the Web Push standard. The job checks the user is still active.
- Errors as in goal 7.

### Service worker (`frontend/public/sw.js`)

- `push`: show a notification with the payload's title and body, icon `/icons/icon-192.png`, and the link kept in `data`.
  - *Claude's call:* `tag` is the link, so repeated pushes about the same task replace each other instead of piling up.
- `notificationclick`: focus an open MegooColab window and navigate it to the link, or open a new one.
- Service-worker registration stays production-only, so push can't be tried under `next dev` (`npm run build && npm start`, or the Docker stack, is needed). The e2e stack is production.

### Frontend

- **`NotificationPrefs`:**
  - a **Push** column, with checkboxes labelled `Push: <kind>`;
  - the page subtitle becomes "Choose what reaches you in the app, by email and as push notifications. Email is sent only when an admin has set up SMTP."
- **`PushDevices` card** above the table, as in the approved mockup.
  - **Turn on:** request permission, then `pushManager.subscribe({userVisibleOnly: true, applicationServerKey})`, then POST.
  - **Turn off:** unsubscribe, then DELETE.
  - Push checkboxes can be ticked whether or not this device is on: they're per person, and the card is per device.

## Release

MegooColab-only (no runner change). When released, a **minor** bump. The release note says push needs HTTPS (all real installs have it), works on desktop browsers and Android, and on iPhone only after adding MegooColab to the Home Screen.

## Left to the builder

- Exact route names, if notification routes already follow a pattern.
- Where the VAPID keys live (an org-settings column or a small table) and their encryption helper.
- Turning the user agent into a device name.
- **Tests:**
  - prefs carry `push` and default off;
  - `notify` enqueues push only when ticked;
  - the job sends to every subscription, deletes on 410 and raises on 5xx;
  - subscription register, re-register and delete, including moving an endpoint between users;
  - the service worker's push and click handlers, at least by a unit test of the handler functions;
  - the card's states (on, off, blocked, unsupported, iOS not installed).
