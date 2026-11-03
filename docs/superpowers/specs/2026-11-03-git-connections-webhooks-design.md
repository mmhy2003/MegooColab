# Git connections and per-repository webhooks (piece 1 of 4)

Status: approved in conversation with the owner (mockups: `.superpowers/brainstorm/1176-1793711513/content/`,
`git-flow.html`; git-ignored). This is the first of four pieces; the later ones are listed at the end so this one
builds what they need.

## Why

The owner connects GitHub.com, GitLab.com and a self-hosted GitLab. Setting them up today is confusing and manual:

- **Server address.** Adding a provider asks for a base URL even for GitHub.com and GitLab.com, where it can only be
  one value, and picking the kind doesn't fill it in.
- **Shared webhook secret.** The webhook secret lives on the provider, so every repository shares one address and
  one secret.
- **Repositories typed by hand.** A project's repositories are typed in (name, URL, default branch) even though the
  provider's token could list them.
- **No help with webhooks.** Nothing helps register a repository's webhook on GitHub or GitLab, or shows whether it
  works.

The larger goal, pieces 2–4, is to follow what people and agents do on a task's pull request and branch, and to act
on it. That needs a reliable webhook per repository, receiving more events than today.

## Goals

1. **Adding a provider asks only what it must.** The admin picks the kind (GitHub, GitLab, Gitea/Forgejo):
   - GitHub and GitLab then offer hosted or self-hosted. Hosted (GitHub.com, GitLab.com) needs no server address.
     Self-hosted (GitHub Enterprise Server, a GitLab instance) asks for it.
   - Gitea/Forgejo is always self-hosted, so it always asks for the address.

   The form keeps Name and Access token and drops the webhook secret. The token field says what access is needed:
   - **Read:** list repositories and read pull requests (GitHub: a fine-grained token with Contents, Metadata and
     Pull requests read, or classic `repo`; GitLab: `read_api`; Gitea: read repository).
   - **Optional, for one-click webhook setup:** manage webhooks (GitHub: Webhooks read/write, or classic
     `admin:repo_hook`; GitLab: `api` with Maintainer on the project; Gitea: write repository).

   Each kind links to how to make such a token.
2. **A project's repository is picked, not typed.** In Project › Settings › Repositories, Add first chooses a
   provider connection.
   - A searchable list shows the repositories its token can see: the full path, plus the default branch where the
     provider gives it. Picking one fills in name, URL and default branch, and the default branch stays editable.
   - "Enter it by hand" keeps today's form, for plain git servers or a repository the token can't list.
   - Repositories without a connection (plain git) behave exactly as today.
3. **Each repository has its own webhook.** A repository with a connection gets its own webhook address and its own
   generated secret. Its row has a **Webhook** button (or **Set up webhook** while none has arrived) that opens a
   dialog with:
   - **Address and secret:** the payload URL (`<public_url>/api/git/webhooks/repos/<repo id>`) and the secret, each
     with Copy. The secret is hidden until Show.
   - **Make a new one:** regenerates the secret, after a confirmation saying the old one stops working at once.
   - **The steps for that host**, in its own words, and a link to the host's webhook page for that repository:
     - GitHub: Settings › Webhooks › Add webhook; content type `application/json`; individual events: Pull
       requests, Pull request reviews, Pull request review comments, Issue comments, Pushes, Check runs, Check
       suites, Statuses.
     - GitLab: Settings › Webhooks; Secret token; triggers: Push events, Comments, Merge request events, Pipeline
       events.
     - Gitea/Forgejo: Settings › Webhooks › Gitea; content type JSON; events: Push, Pull request, Pull request
       review, Pull request comment, Issue comment, Status (custom events).
   - **Create it for me:** registers the webhook on the host with exactly that address, secret and events, through
     the host's API and the connection's token.
     - It succeeds when the token may manage webhooks.
     - A refusal (no permission, not found) says what's missing in plain words, and leaves the manual steps
       available.
     - **No duplicates** *(my call)*. It first lists the repository's webhooks on the host:
       - one at this repository's own address (MegooColab's earlier one, or one a person added from the manual
         steps) is updated in place, not duplicated;
       - one at the connection's old shared address (`/api/git/webhooks/<connection id>`) is removed, since both
         point at MegooColab and every event would otherwise arrive twice;
       - webhooks pointing anywhere else are never touched.

       Its own webhook's id is saved, so later changes can find it without listing.
4. **You can see whether it works.** Each repository with a connection shows one of the following. Only deliveries
   to the repository's own address count *(my call)*: deliveries to the old shared address don't, so "not set up"
   honestly means "still relies on the shared webhook, if anything".
   - "Webhook not set up": nothing received yet;
   - "Webhook working · last event <time ago>";
   - "Webhook failing": the last delivery's signature was wrong. This is shown after a bad delivery for a
     repository whose own secret exists, and cleared by the next good one.

   The dialog updates live when the first event arrives, for example GitHub's ping on creation.
5. **Nothing that works today breaks.**
   - Webhooks already registered at a connection's old address (`/api/git/webhooks/<connection id>`) with its old
     secret keep being accepted while that connection still has a secret.
   - The provider form no longer offers the secret. A connection that still has one shows a notice: "This provider
     still has a shared webhook secret from before. Repositories now each have their own: set them up, then remove
     the shared one." It also offers a **Remove shared secret** button.
   - *(My call:)* the notice lists the repositories on that connection, across projects, whose own webhook hasn't
     received anything yet. While any remain, Remove asks first: "These repositories haven't set up their own
     webhook yet and would stop getting updates."
   - **When the repository changes** *(my call)*:
     - **Make a new one** (a new secret): when MegooColab created the repository's webhook (its id is saved), the new
       secret is also sent to that webhook on the host. When it can't be (no record, no permission, the host
       refuses), the dialog says to update the secret on the host, or to use Create it for me.
     - **Unlinked from its connection, moved to another connection, or the repository removed:** the webhook
       MegooColab created for it is deleted from the host on a best-effort basis. A failure is reported but never
       blocks the change. The repository's secret, saved webhook id and status are cleared, and a later connection
       starts fresh.
   - **Getting a connection without the picker** *(my call)*: the per-row connection choice stays for existing and
     hand-entered repositories, and the "Enter it by hand" form also takes an optional connection, so a repository
     the token can't list can still be tracked and get a webhook.
   - Pull request tracking (the current refresh, polling and Mark merged) keeps working for every repository,
     whether its webhook is old-style, per-repository or missing.

## Non-goals (this piece)

- Recording PR, push, comment or review events on the task (piece 2). This piece verifies and accepts those
  events, and records only that a delivery arrived (for the status in goal 4). Deliveries keep triggering today's PR
  refresh.
  - *(My call:)* it also keeps each delivery's host-given id (GitHub `X-GitHub-Delivery`, GitLab
    `X-Gitlab-Event-UUID`, Gitea `X-Gitea-Delivery`) for a while and ignores a repeat, so piece 2 never records an
    event twice.
- Acting on reviews (piece 3), agent PR review (piece 4), merging.
- OAuth apps / GitHub App installation: tokens stay personal or bot access tokens pasted by an admin.
- Bitbucket or other hosts.

## Anti-goals

- Showing a token or a webhook secret where it isn't needed: tokens stay write-only. A repository's secret is
  shown only in its Webhook dialog, to people who manage the project, and only after Show.
- Breaking a project's existing repositories or tracked pull requests on upgrade.
- A one-click setup that creates duplicate webhooks, or changes a webhook that points anywhere but MegooColab. Webhooks
  at MegooColab's own addresses are MegooColab's to update or remove.

## Constraints

- **Where it lives:** backend in `backend/app/git` and `backend/app/projects`; frontend in Admin › Git
  (`GitConnections.tsx`) and Project › Settings › Repositories (`RepoEditor.tsx`). Migrations are generated against
  `megoo_migrate` only.
- **Secrets:** encrypted at rest like the existing ones (`encrypt`/`decrypt`), 32 random bytes, URL-safe base64.
- **Webhook verification**, the same rules as today, per kind:
  - GitHub and Gitea: `X-Hub-Signature-256` HMAC of the raw body;
  - GitLab: the `X-Gitlab-Token` header equal to the secret;
  - the same size limit and rate limits. Unknown repositories and bad signatures count against the sender's
    address, as today.
- **Hosts:** "hosted" means `https://github.com` (API `https://api.github.com`) and `https://gitlab.com`.
  Self-hosted GitHub uses `<address>/api/v3`, as `providers.api_base` already does.
- **Who can do what:** project managers can list a connection's repositories when adding one, open the Webhook
  dialog, make a new secret and use Create it for me. Admins manage connections. Listing repositories never returns
  the token.
- **Repository listing:**
  - Calls the host's API with the connection's token: GitHub `GET /user/repos` (owned, collaborator and
    organization member, paginated); GitLab `GET /projects?membership=true&simple=true`; Gitea `GET /user/repos`.
  - It is paged and searchable on the server side when the host supports it. The UI searches as you type, with a
    short debounce, and the first page appears without typing.
  - The repository's URL is stored as its https web URL (what `providers.repo_path` already understands).
- **Public address:** the webhook address uses the app's configured `public_url`. If that is still the
  `http://localhost:8080` default, the dialog warns that the host can't reach it.

## Data (the builder's to shape; what it has to hold)

- **On a repository:**
  - its own webhook secret (encrypted, null until first made);
  - when a webhook delivery last arrived, and whether the last one was rejected for its signature;
  - the id of the webhook MegooColab created on the host, if any (so Create it for me can replace it).
- **On a connection:** the hosted or self-hosted choice can be derived from the base URL. The base URL stays stored:
  for hosted ones it is set to the canonical address, so existing code (PR URL parsing, `api_base`) is unchanged.

## For the later pieces (so this one receives what they need)

- **Piece 2:** a task's Activity shows pushes, PR opened or updated, comments, reviews, checks, and merged or closed,
  each with its actor (person or agent) and its host. Needs: push, PR, comment, review and check events, which this
  piece subscribes to.
- **Piece 3:** a "changes requested" review, or a comment starting with `/fix`, sends the task back to Build. The
  agent fixes, pushes, and the PR updates. At most 3 rounds, then it asks the human. A project checkbox turns it on.
- **Piece 4:** the project setting "Pull request review: None / Human / Agent" replaces "Require human code review
  before Done".
  - None and Human match today's off and on, and existing projects map to them.
  - With Agent, the reviewer agent (the task's own agent in a fresh session by default, or a chosen one) posts its
    review on the PR, and on approval merges the PR itself; the task is then Done.
  - Its token then needs write access to pull requests (review and merge). The token help in goal 1 should already
    mention it as optional: "for an agent to review and merge".

## Testing

- **Backend:**
  - the new provider fields and defaults for hosted and self-hosted;
  - repository listing per kind (the host's HTTP mocked, pagination and search);
  - the per-repository secret (made, regenerated, never in listings);
  - the per-repository webhook (accepted with the right signature, rejected otherwise, status updated);
  - the old per-connection webhook still accepted;
  - Create it for me per kind (creates, replaces its own, refuses clearly without permission);
  - the migration keeps existing data.
- **Frontend:** unit tests for the provider form (the address appears only for self-hosted and Gitea), the
  repository picker (search, pick fills the fields, enter by hand), and the Webhook dialog (copy, show, make a new
  one, per-host steps, status).
- **e2e:** the existing git spec keeps passing. Add a provider with a fake host, as the existing git e2e does, then:
  - pick a repository from the list;
  - open its Webhook dialog;
  - post a correctly signed delivery to its address;
  - see the status turn to working.

## Left to the builder

- Exact component split, endpoint paths beyond the webhook address above, the debounce and page sizes.
- How the dialog learns the first delivery arrived (refetch on an interval while open, or the existing live events).
- Copy wording beyond what is quoted here, in the app's plain style.
