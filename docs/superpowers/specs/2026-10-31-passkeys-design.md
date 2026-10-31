# Passkeys as a second sign-in factor — design

Status: approved layouts (mockups, 2026-10-31); this document awaits the owner's review.

Build order: after the remembered-accounts change (`feat/remembered-accounts`) is merged into `develop`; the
second step reuses its chosen-account header in `LoginForm`.

## Why

Two-factor sign-in today means typing a 6-digit code from an authenticator app after the password. The owner wants
a faster second step: a **passkey** (the device's fingerprint, face, PIN, or a security key). After the right
password, a person with two-factor sign-in confirms it is them **either** with a passkey **or** with an
authenticator code.

## Goals

- A person can add passkeys to their account and use one, instead of an authenticator code, as the second step of
  signing in.
- Two-factor sign-in is **on** when the person has an authenticator app, at least one passkey, or both.
- The second step offers the passkey first and the code as a fallback (layout A, below).
- Passkeys are managed on **Profile › Two-factor sign-in**, next to the authenticator app.

## Non-goals

- **Passwordless sign-in** (a passkey instead of the password). The password stays the first step. Passkeys are
  created so a later passwordless feature could reuse them (resident keys preferred), but nothing here signs in
  without a password.
- Renaming a passkey after it is added (remove and add again).
- Requiring two-factor sign-in for everyone (an org-wide policy).
- Passkeys for the runner or MCP access tokens.

## Anti-goals (would make this a failure even if it works)

- Revealing, before the right password, whether an account has passkeys or which kind of second step it uses.
- A second factor that is weaker than today's: a passkey must be checked against a fresh, single-use challenge
  bound to that account, with the browser's origin checked.
- Locking out a person who has an authenticator app because their passkey device is not at hand, or the other way
  round: either factor they have set up must work.
- The authenticator-code sign-in changing for people who never add a passkey.

## The person's experience

### Signing in (layout A: passkey first, code as a fallback)

1. Email and password as today (or a remembered account and its password).
2. If the account has two-factor sign-in, the card switches to **Confirm it's you** with the account at the top:
   - **With at least one passkey:** a key icon, "Your browser asks for your passkey: fingerprint, face, PIN or
     security key.", a **Use passkey** button, and — only if they also have an authenticator app — the link
     **Use an authenticator code instead**. The browser's passkey prompt opens by itself when the step appears;
     if it is dismissed or fails, **Use passkey** tries again.
   - **Authenticator app only:** the code field, as today.
3. A failed or cancelled passkey prompt says so plainly ("The passkey wasn't used. Try again, or use your
   authenticator code."), and never signs in.

### Profile › Two-factor sign-in

- **Authenticator app** section: unchanged (set up / turn off).
- **Passkeys** section, under it: a short explanation, the list of passkeys (an icon, the name, "Added <date> ·
  last used <date | never>", **Remove**), and **Add a passkey**.
  - **Add a passkey:** the browser creates the passkey (its own prompt), then MegooColab asks for a name, prefilled
    with a guess from the device ("Windows", "iPhone", "Security key"), up to 100 characters.
  - **Remove:** asks for the password **and** a second factor (a passkey prompt, or an authenticator code if they
    have an app), as turning off the authenticator app asks for the password and a code today. So removing the last
    passkey can never turn two-factor sign-in off with only a session and a password.
- A line at the top says whether two-factor sign-in is on, and that it is on as long as either method is set up.

## Decisions made with the owner

- Passkeys are a **second factor**, alternative to the authenticator code (owner).
- Layout A for the second step: passkey first, code as a fallback link (owner).
- Passkeys are managed in Profile › Two-factor sign-in, under the authenticator app (shown in the mockups, approved
  with layout A).
- **Recovery (owner, option a):** an admin can turn off another person's two-factor sign-in, so someone who has
  lost every second factor (a lost phone, or passkeys broken by a change of the server's address) gets back in.

## Calls made by the designer (owner to check)

- **Libraries.** Backend: `webauthn` (py_webauthn, Duo Labs) for creating options and verifying responses.
  Frontend: `@simplewebauthn/browser` for the browser ceremony (base64url handling, error mapping). Both pinned to
  exact versions.
- **Relying party.** RP ID is the host of `PUBLIC_URL`; the expected origin is `PUBLIC_URL`'s origin. The RP name
  is the organization's name (falling back to "MegooColab"). Passkeys need HTTPS (or `localhost`), as push does.
  Changing the server's host name makes existing passkeys stop working (documented for admins in docs/install.md).
- **Creation options.** Attestation `none`; resident key `preferred`; user verification `preferred`; the person's
  existing passkeys are excluded (no duplicates on one authenticator). Algorithms: ES256 and RS256.
- **Sign-in options.** `allowCredentials` lists that account's passkeys (the account is known after the password);
  user verification `preferred`; timeout 2 minutes.
- **Challenges** live in Postgres, not Valkey: Valkey is optional (the app runs with "limits off" without it), and
  passkey sign-in must not depend on it. A `webauthn_challenges` table holds one row per purpose and account
  (`register`, `login`, `remove`), each valid 5 minutes and deleted the moment it is used, successful or not;
  expired rows are deleted when a new challenge is made.
- **Sign counter.** Stored and checked as the library recommends; a counter that goes backwards (a cloned
  authenticator) fails the sign-in and is written to the audit log.
- **Rate limits.** Failed passkey sign-ins count against the same per-account limit as wrong authenticator codes
  (`totp_account`, renamed in the code to a second-factor limit, same setting), and against the per-address login
  limit, exactly as a wrong code does today.
- **Audit log.** `auth.passkey_added`, `auth.passkey_removed`, and the existing `auth.login` / `auth.login_failed`
  rows carry which second factor was used (`totp` | `passkey`).
- **At most 10 passkeys per account** (409 `too_many_passkeys`).

## Recovery: turning off someone's two-factor sign-in

- **Admin › Users**, on another person's row: **Turn off two-factor sign-in** (shown only when that person has it
  on). A confirmation dialog names the person and says what happens: their authenticator app and all their passkeys
  are removed, they sign in with their password alone and can set two-factor up again from their profile.
- It clears `totp_enabled` and `totp_secret_enc` and deletes all their passkeys and challenges, in one transaction.
  Their sessions stay (they are not suspected of anything; the admin can still revoke them as today).
- Audit: `auth.two_factor_reset`, actor the admin, target the person. If email is set up, the person gets an email
  ("<admin> turned off two-factor sign-in for your MegooColab account. If you didn't ask for this, tell them."); the
  reset does not fail when email isn't set up.
- An admin can't use it on themselves (409 `cannot_reset_own_two_factor`): their own profile turns it off.
- **For a locked-out sole admin**, or after a change of address locks out every admin: a server command,
  `docker compose exec backend python -m app.cli reset-two-factor <email>`, does the same (audit actor: none,
  `"via": "cli"`), documented in `docs/install.md` next to the host-name warning.

## How it fits the code

### Data

A new table `passkeys` (named constraints, one Alembic migration, generated against `megoo_migrate`):

| column | type | notes |
| --- | --- | --- |
| id | uuid | primary key |
| user_id | uuid | FK users, `ON DELETE CASCADE`, indexed |
| credential_id | bytea | unique |
| public_key | bytea | COSE key from registration |
| sign_count | integer | |
| transports | jsonb | list of strings, as the browser reported |
| aaguid | text, nullable | for the device-name guess |
| name | varchar(100) | |
| created_at | timestamptz | `now()` |
| last_used_at | timestamptz, nullable | |

A second new table `webauthn_challenges`: id, user_id (FK users, cascade), purpose (`register` | `login` |
`remove`), challenge (bytea), expires_at; unique on (user_id, purpose), so a new challenge replaces the old.

`users.totp_enabled` stays as it is. "Two-factor on" is computed: `totp_enabled or has passkeys`.

### API (all under `/api/auth`)

- `POST /login` — unchanged body plus an optional `passkey` (the assertion JSON from the browser). After the right
  password, for an active account with two-factor sign-in and no second factor in the request:
  - only an authenticator app → 401 `totp_required` (unchanged, so older clients keep working);
  - any passkey → 401 with `detail: "second_factor_required"`, `methods: ["passkey"]` or `["passkey", "totp"]`, and
    `passkey_options` (the request options with a fresh challenge). The frontend shows the step from `methods`.
  - With `passkey` in the request: verify it against the stored challenge for that account (consumed), the expected
    origin and RP ID, one of the account's credentials and its counter; on success update `sign_count` and
    `last_used_at` and sign in. With `totp_code`: as today. A request may carry either.
  - Everything that today happens on a wrong code (lockout counting, audit, guards) happens on a failed passkey.
- `GET /passkeys` — the current person's passkeys: id, name, created_at, last_used_at (no key material).
- `POST /passkeys/options` — creation options with a fresh `register` challenge.
- `POST /passkeys` — `{name, credential}`: verifies the registration and stores it.
- `POST /passkeys/{id}/remove-options` — request options with a fresh `remove` challenge (for the passkey prompt
  of the removal dialog).
- `DELETE /passkeys/{id}` — body `{password, passkey?, totp_code?}`: the password and one second factor, as
  `/totp/disable` asks for the password and a code; a wrong one fails like a wrong code there (the same checks and
  counting); 404 for someone else's passkey.
- `GET /me` (`UserOut`) gains `passkey_count`, so the profile and the second step know what to show.
- `POST /api/admin/users/{id}/reset-two-factor` (admins, not on themselves); the admin users list shows whether each
  person has two-factor sign-in on (`two_factor: bool` on the admin user rows).

Errors get messages in `frontend/src/lib/errors.ts` (`second_factor_required` is handled by the login form, not
shown).

### Frontend

- `LoginForm`: a third state after the password, **Confirm it's you**, driven by the 401's `methods` /
  `passkey_options`; the remembered-accounts header (the chosen account at the top) is reused.
- `settings/profile`: the Two-factor tab gets the Passkeys section (list, add, remove with a password dialog).
- `@simplewebauthn/browser`'s `startRegistration` / `startAuthentication`; its errors map to plain messages
  ("This device already has a passkey for your account.", "The passkey wasn't used.").

## Testing

- Backend (pytest): registration and sign-in with py_webauthn test vectors or a software authenticator; a replayed
  challenge, a wrong origin, someone else's credential and a counter that goes backwards all fail; the old
  `totp_required` path is unchanged for accounts without passkeys; removing needs the password; the rate limit and
  lockout count failed passkeys.
- Frontend (vitest): the second step's three shapes (passkey only, both, code only), the fallback link, the
  dismissed-prompt message, the Passkeys section.
- Recovery: the admin reset removes both kinds and the person then signs in with the password alone; not on
  oneself; the CLI command; the audit row.
- End-to-end (Playwright): Chromium's virtual authenticator (CDP `WebAuthn.addVirtualAuthenticator`) adds a passkey
  on the profile page, signs out, signs in with password + passkey, then with the code fallback, then removes the
  passkey.

## Open questions for the owner

- None.

## Left to the builder

- Exact component structure, copy within the tone of the mockups, the device-name guess table (AAGUID / user agent),
  and how the passkey prompt is retried.
