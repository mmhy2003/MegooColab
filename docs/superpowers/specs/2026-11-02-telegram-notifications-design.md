# Telegram notifications

Status: draft for the owner's review. Builds on develop after the logo, mentions and read-on-act fixes.

## Why

One of the owner's users asked to get MegooColab notifications in Telegram. Today a person chooses, per kind of
notification, whether it reaches them in the app, by email or as a browser push
(`backend/app/notifications/models.py`: `NotificationPref.in_app/email/push`, five kinds: needs you, assigned,
mentioned, agent offline, question waiting). Telegram becomes a fourth way, alongside those three.

## Goals

- A site admin sets up one Telegram bot for the whole site.
- Each person links their own Telegram account from Settings › Notifications and picks, per kind, whether it reaches
  them in Telegram.
- A Telegram message carries the notification's title and short text and a button that opens the task, chat or
  question it is about.
- It works on a server that cannot be reached from the internet.

## Non-goals

- Replying, approving or answering from Telegram. Messages are one way.
- Telegram group chats or channels; only a person's private chat with the bot.
- Sending to anyone who has not linked their own account.
- More than one bot per site.

## Anti-goals

- Leaking more through Telegram than the app's notifications already show: no code, secrets, whole comments or
  documents. Only the notification's title (≤ 200 chars) and body (≤ 500 chars) as stored today.
- Linking the wrong account: a person must only ever link their own Telegram chat to their own MegooColab account.
- Messages going on after a person disconnected, blocked the bot, or the admin removed the bot.

## How it works (decided with the owner)

### The admin sets up the bot

- The admin creates a bot with Telegram's @BotFather and pastes its token into **Admin › Settings**, in a new
  **Telegram** tab (next to Email). The token is a secret: stored encrypted like the SMTP password
  (`app/core/crypto.encrypt`, `OrgSettings`), never sent back to the browser (only "set" / the bot's @username).
- There is one `OrgSettings` row (`ORG_SETTINGS_ID`): one bot for the site.
- Saving checks the token with Telegram (`getMe`) and shows the bot's @username. A token Telegram refuses is not saved
  ("Telegram doesn't accept this token"); nor is one that cannot be checked because Telegram cannot be reached from
  the server ("Couldn't reach Telegram from the server") — such a server could not send to Telegram anyway.
- A **Remove** button clears the token: Telegram stops for everyone. People's links and Telegram choices are kept
  for when a bot is set again only if it is the same bot (same bot id). Setting a different bot clears every link and
  every unused link code, and starts reading its messages afresh (the stored `getUpdates` offset is reset); people's
  Telegram choices stay, unused until they link again.
- With no bot set, Settings › Notifications shows no Telegram column.

### A person links their account

- Settings › Notifications gets a **Telegram** section: "Connect Telegram" makes a one-time link code (random, valid
  15 minutes, one person) and opens `https://t.me/<bot username>?start=<code>`. In Telegram, the person presses
  Start; the bot receives `/start <code>`, links that private chat to the code's person, and replies "Connected to
  MegooColab as <name>." The page shows "Connected" (it refetches while waiting).
- A `/start` with an unknown, used or expired code gets "This link has expired. Open MegooColab › Settings ›
  Notifications and press Connect Telegram again." Anything else sent to the bot gets a one-line reply that the bot
  only sends notifications.
- **Disconnect Telegram** removes the link. Blocking the bot in Telegram has the same effect: the first failed send
  with Telegram's "blocked by the user" (HTTP 403) removes the link.
- One Telegram chat per person; linking again replaces the old chat. One chat may belong to only one person: linking
  a chat already linked to someone else moves it (the earlier person is unlinked).

### Choosing what goes to Telegram

- The preferences table gets a fourth column, **Telegram**, per kind (`NotificationPref.telegram`, default off).
  Its boxes are disabled with "Connect Telegram first" until the person is linked.
- **On linking (owner-approved default):** Telegram switches on for the kinds the person currently gets as push; if
  none, for **needs you** and **mentioned**. They can change any kind afterwards.
- That default applies only the first time a person links (when none of their kinds has Telegram on). Disconnecting,
  being blocked-out, or losing the chat to someone else keeps their choices; linking again uses them as they are.

### Sending

- `notifications.notify` already decides, per recipient and kind, in-app / email / push. It also enqueues one
  `notify.telegram` job per recipient whose Telegram is on for that kind and who is linked, with the title, body
  and link — the same rules as push (readability, never to the actor). The "no repeat within 10 minutes" check in
  `notify` already drops a repeat for every way at once (it is per person, kind and task, not per way): Telegram
  follows it, with no state of its own.
- The job sends `sendMessage` to the person's chat: the title in bold, the body under it (both escaped for
  Telegram's HTML parse mode), and an inline button "Open in MegooColab" to the site's public URL + the link.
  The button is added only when `settings.public_url` is `https` with a host Telegram can open (not `localhost`, not
  a bare name without a dot, not a private or loopback IP address); otherwise the message has no button and ends
  with the full URL as text. If Telegram still refuses the message because of the button (400 mentioning the
  button/URL), it is sent once more without it.
- A failed send is retried like the email and push jobs, except 403 (blocked / chat gone: unlink, no retry) and 400
  "chat not found" (unlink, no retry). 429 waits the `retry_after` Telegram gives.

### Hearing the Start presses (decided: no inbound connection)

- MegooColab asks Telegram for new messages itself (`getUpdates` long polling, offset kept in the database), from the
  worker, only while a bot is set. No webhook, so it works behind a firewall or on a laptop.
- The long poll runs as its own task beside the worker's job loop, so its ~30-second waits never hold up jobs.
- The deployment runs one worker container, but only one poller may run per bot (Telegram answers a second one
  with 409): the poller holds a Postgres advisory lock while it polls, and a worker without the lock does not poll.
- Only private chats' `/start` messages are acted on; everything else gets the one-line reply or is ignored.

## Constraints

- Backend: FastAPI + SQLAlchemy + the existing jobs queue/worker (`app/jobs`); one Alembic migration (the new
  columns/tables), run against `megoo_migrate` only.
- HTTP to Telegram: `https://api.telegram.org/bot<token>/<method>`, through the HTTP client the backend already uses;
  the token never appears in logs, errors shown to the admin, or audit data.
- Frontend: Next.js; the existing Admin › Settings tabs and Settings › Notifications page.
- Audit: setting/removing the bot token (actor: the admin) and linking/unlinking a person (actor: that person) are
  audit events, like other settings. An unlink MegooColab makes itself (the person blocked the bot, the chat moved to
  someone else, a different bot was set) is recorded with no actor and the reason.
- Tests must not call Telegram: the client is replaceable in tests.

## Calls I made (the owner can overrule)

- Link codes last 15 minutes and work once.
- Replacing the bot with a different one unlinks everyone (their chats belong to the old bot).
- Without a public site URL there is no button; the path is printed instead.
- The bot answers anything other than a valid `/start` with one line, never silence.
- A token that cannot be checked is not saved.
- The button is left out for a local, private or plain-http site address, and dropped on a retry if Telegram refuses
  it.
- The first-link default applies once; later links keep the person's choices.
- A different bot unlinks everyone and resets the message offset; choices are kept.
- One poller at a time, through a Postgres advisory lock.

## Left to the builder

- Table and column names, the shape of the link-code storage, how the long-poll loop sits in the worker.
- Exact copy beyond the strings above, the Telegram section's layout.
- Message formatting details within "title bold, body, button".
