# Tool Hub, part 1: the library and sharing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each person keeps their MCP servers (with encrypted secrets) and skills in a Tool Hub library. They can share
them without secrets to teams, to people or to everyone. They can take copies of what others share, and admins can
moderate shared tools.

**Architecture:** This is part 1 of 2. Part 2 (plan 24) pushes the library to machines through the runner.
- **Backend:** a new `app/hub` module (models, pure rules, service, router, admin router) plus one org setting.
  - A tool's **setup** is a neutral JSON `spec`.
  - Its **secret values** live in one Fernet-encrypted column.
  - A skill's files are rows in `hub_tool_files`.
- **Frontend:** a `lib/hub.ts` data module, the `/hub` pages and an `/admin/hub` page.
- Nothing in this plan talks to the runner.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, pytest; Next.js App Router, TanStack Query, Tailwind, Vitest +
Testing Library, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-01-tool-hub-design.md`

## Global Constraints

- **Branch:** `feat/plan-23-tool-hub-library`, cut from `develop` at `4739719`.
- **Secrets never leave the owner.** No response, log line, audit `data` or error detail contains a secret value. This
  plan has no decrypting read path at all; plan 24 adds the one to the owner's runner. Responses only say whether each
  secret slot is set: `secrets: [{name, set}]`, where `set` is always `false` for anyone but the owner.
- **Tool names** match `^[a-z0-9][a-z0-9_-]{0,63}$`, are unique per owner, and are used as-is as the MCP server name
  and the skill folder name.
- **Placeholders** look like `${NAME}`, where NAME matches `[A-Z0-9_]+`. They are allowed in the URL and in command
  arguments, and must name a secret slot (a header or environment entry with `secret: true`).
- **Skill limits:**
  - at most 100 files;
  - at most 1 MiB per file and 2 MiB in total;
  - a `SKILL.md` at the root;
  - no absolute paths, `..`, drive letters or empty segments.
- **Script files are those whose extension is one of:**
  - `.sh` `.bash` `.zsh`: run on `linux` and `macos`;
  - `.ps1` `.bat` `.cmd`: run on `windows`;
  - `.py` `.js` `.mjs` `.cjs` `.ts` `.rb` `.pl`: run on all three.
- **Org setting** `hub_share_everyone`, default `true`.
  - When it's off, the Everyone shelf is empty and new shares to everyone are refused.
  - Existing shares to everyone are kept, just not shown.
- **Error codes** (detail strings), each also added to `frontend/src/lib/errors.ts` `MESSAGES`:

  | Code | Message |
  |---|---|
  | `hub_name_taken` | You already have a tool with that name. |
  | `hub_bad_name` | Use lowercase letters, digits, - and _ (up to 64). |
  | `hub_unknown_placeholder` | A ${…} placeholder doesn't match any secret. |
  | `hub_flagged_values` | Some values look like keys. Mark them secret or confirm they aren't, then share. |
  | `hub_everyone_off` | Sharing with everyone is turned off on this MegooColab. |
  | `hub_team_not_member` | You can only share with teams you belong to. |
  | `hub_already_copied` | It's already in your library. |
  | `hub_removed` | An admin removed this tool. |
  | `hub_copy_read_only` | This is a copy. Make it your own to change it. |
  | `hub_skill_too_large` | The skill is too big (2 MB in all, 1 MB per file). |
  | `hub_too_many_files` | A skill can have at most 100 files. |
  | `hub_skill_no_skill_md` | A skill needs a SKILL.md at its top level. |
  | `hub_bad_path` | One of the file paths isn't allowed. |
  | `hub_no_update` | There's no newer version. |

- **UI copy, exactly:**
  - the sidebar label is `Tool Hub`;
  - the tabs are `Mine`, `Shared with me`, `Everyone`;
  - the buttons are `Add MCP`, `Add skill`, `Add to my library`, `Take update`, `Make it my own`, `Share`;
  - the states are `key missing`, `Update available`, `no longer shared`, `removed by an admin`;
  - the switch label is `Safe in read-only runs`, with the help text `Turn this on only for tools that read and
    never change anything outside.`;
  - the script warning is `This skill includes files your agents may run on your machine:` followed by the list.
- **Audit actions:** `hub.tool_shared`, `hub.tool_unshared`, `hub.tool_removed`. Their `data` carries
  `{name, teams, users, everyone}`, never a value from the spec.
- **Migrations:** generate them only against `megoo_migrate` (the backend README's `DEV_DATABASE_URL=… megoo_migrate
  bash scripts/makemigration.sh`). Give every FK, unique and check constraint an explicit Postgres-style name, in both
  upgrade and downgrade. Check with `alembic downgrade -1 && alembic upgrade head`.
- **Tests and tooling:**
  - Backend: `cd backend && uv run pytest <path>`. Never run two pytest runs at once. Lint with
    `uv run --with ruff ruff check <files>`.
  - Frontend: `cd frontend && npx vitest run <path>`, then `npx eslint <paths>` and `npx tsc --noEmit`. Do not run
    Prettier: the repo uses about 120-column lines.
  - API types: `npm run gen:api`, after every backend schema change the frontend uses.
  - End to end: only the `megoo-e2e` compose project.
- **Commits:** every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A secret's value reaching a non-owner** through any read: tool detail, list, copy, admin list, audit, or a 422
   echoing input. Task 2 asserts the raw value never appears in any response body, for owner reads too, apart from
   `set`.
2. **A copy taken before the source changed its secret slots** (renamed or removed a secret header). Taking the update
   keeps values only for slot names that still exist and shows `key missing` for new ones. Test in Task 5.
3. **Zip entries with tricky paths** (`../x`, `C:\x`, `/etc/x`, `a//b`, a top folder wrapping everything). The bad ones
   are refused; a single top folder is stripped. Tests in Task 3.
4. **A tool shared to a team when a viewer later leaves the team.** Visibility follows current membership at read
   time, so the tool drops off their shelf and a direct link is a 404. Test in Task 4 (`test_left_team_loses_access`).
5. **An admin removing a tool whose copies were already "made my own".** Those are no longer copies and stay
   untouched; only live copies are marked. Test in Task 6.

---

### Task 1: Hub data model, rules and migration

**Files:**
- Create: `backend/app/hub/__init__.py`, `backend/app/hub/models.py`, `backend/app/hub/rules.py`, `backend/app/hub/schemas.py`
- Modify: `backend/app/models.py` (import `app.hub.models`), `backend/app/org/models.py` (column `hub_share_everyone`)
- Create: `backend/migrations/versions/<rev>_tool_hub.py`
- Test: `backend/tests/hub/__init__.py`, `backend/tests/hub/test_rules.py`

**Interfaces:**
- Produces (models, `app/hub/models.py`):
  - `HubTool(IdMixin, TimestampMixin, Base)`, table `hub_tools`, with columns:
    - `owner_id` (FK users, CASCADE, indexed)
    - `kind: str` (`"mcp"|"skill"`)
    - `name: String(64)`
    - `description: Text = ""`
    - `version: int = 1`: bumps on a change to the setup, the files or the description
    - `rev: int = 1`: bumps on any change, including secrets and `read_only_safe`
    - `spec: JSONB | None`: MCP only, with secret values stored as `""`
    - `secrets_enc: Text | None`
    - `read_only_safe: bool = False`
    - `share_everyone: bool = False`
    - `is_copy: bool = False`
    - `source_id` (FK hub_tools, SET NULL)
    - `source_version: int | None`
    - `removed_at: DateTime(tz) | None`
    - `removed_by_id` (FK users, SET NULL)

    Unique constraint `hub_tools_owner_id_name_key` on `(owner_id, name)`.
  - `HubToolShare(IdMixin, Base)`, table `hub_tool_shares`. Columns: `tool_id` (FK CASCADE, indexed), `team_id` (FK
    teams, CASCADE, nullable), `user_id` (FK users, CASCADE, nullable). Check `hub_tool_shares_one_target_check`:
    exactly one of `team_id` and `user_id` is set.
  - `HubToolFile(IdMixin, Base)`, table `hub_tool_files`. Columns: `tool_id` (FK CASCADE, indexed),
    `path: String(255)`, `content: LargeBinary`, `size: int`. Unique `hub_tool_files_tool_id_path_key`.
  - `OrgSettings.hub_share_everyone: Mapped[bool] = mapped_column(default=True, server_default=true())`.
- Produces (schemas, `app/hub/schemas.py`):
  - `Entry(name, value: str = "", secret: bool = False)`. `name` matches `^[A-Za-z_][A-Za-z0-9_-]{0,99}$`; `value`
    is at most 2000 characters.
  - `Command(command: NoNulStr 1..500, args: list[str] ≤ 50, each ≤ 2000)`.
  - `McpSpec`, with fields:
    - `transport: Literal["http","stdio"]`
    - `url: str | None`: required for http, scheme http or https only
    - `headers: list[Entry] = []`
    - `command: Command | None`: the default command for stdio
    - `os_commands: dict[Literal["windows","linux","macos"], Command] = {}`: per-system overrides. A stdio spec needs
      `command`, or at least one `os_commands` entry. A system with neither is "not available" there (plan 24).
    - `env: list[Entry] = []`
    - `acknowledged: list[str] = []`

    Validation: no duplicate entry names; every placeholder names a secret slot (else `hub_unknown_placeholder`).
- Produces (rules, `app/hub/rules.py`, pure functions):
  - `NAME_RE: re.Pattern`, `PLACEHOLDER_RE: re.Pattern` (`\$\{([A-Z0-9_]+)\}`)
  - `secret_slots(spec: McpSpec) -> list[str]`: names of secret entries, headers first, in order
  - `looks_like_secret(value: str) -> bool`: true for:
    - known prefixes (`sk-`, `sk_`, `ghp_`, `gho_`, `github_pat_`, `xoxb-`, `xoxp-`, `glpat-`, `AKIA`, `Bearer `),
      followed by at least 8 more characters;
    - any run of 24 or more characters from `[A-Za-z0-9_\-]` with at least one digit and one letter that isn't a
      placeholder.
  - `flagged_values(spec: McpSpec) -> list[str]`: locations of values that look like secrets and aren't marked secret
    or acknowledged. Locations look like `"url"`, `"args[1]"`, `"windows.args[0]"`, `"headers.X-Key"`, `"env.FOO"`.
  - `script_systems(path: str) -> list[str] | None`
  - `skill_frontmatter(text: str) -> tuple[str | None, str | None]`: the `name` and `description` from the leading
    `---` YAML-ish block, using simple `key: value` lines (no YAML dependency)
  - `normalize_skill_files(entries: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]`: converts backslashes to
    `/`, strips a single common top folder, then enforces the limits. Raises `HTTPException(422 | 413, <code>)` with
    the codes above. Exports the constants `MAX_SKILL_FILES = 100`, `MAX_SKILL_FILE_BYTES = 1 << 20` and
    `MAX_SKILL_BYTES = 2 << 20`.

- [ ] **Step 1: Write the failing tests** in `tests/hub/test_rules.py`
  - `test_names`: `NAME_RE` accepts `context7`, `ui-review`, `a_b`. It rejects `Context7`, `-x`, `a b` and a
    65-character name.
  - `test_spec_placeholders`: an http spec with url `https://x/mcp?key=${API_KEY}` and header
    `Entry(name="API_KEY", secret=True)` validates. The same spec without the secret header raises a ValidationError
    whose message contains `hub_unknown_placeholder`.
  - `test_looks_like_secret`: true for `sk-abcdefgh1234` and `ghp_` + 30 characters. False for `npx`,
    `@upstash/context7-mcp`, `--api-key` and `${API_KEY}`.
  - `test_flagged_values`: these are flagged: a stdio spec with args `["-y","pkg","--key","sk-live1234567890"]` gives
    `["args[3]"]`; an env entry `FOO=ghp_…` not marked secret gives `"env.FOO"`; a url with a 32-character token in its
    query gives `"url"`. Adding `"args[3]"` to `acknowledged` removes that one.
  - `test_script_systems`: `scripts/a.sh` gives `["linux","macos"]`, `run.ps1` gives `["windows"]`, `x.py` gives all
    three, `SKILL.md` gives `None`.
  - `test_frontmatter`: `"---\nname: ui-review\ndescription: Use when…\n---\n# body"` gives
    `("ui-review", "Use when…")`. Text without frontmatter gives `(None, None)`.
  - `test_normalize`:
    - `[("ui/SKILL.md", b"x"), ("ui/a/b.md", b"y")]` becomes `[("SKILL.md", …), ("a/b.md", …)]`.
    - Each of `../x`, `/x`, `C:/x`, `a//b` raises `hub_bad_path`.
    - Missing SKILL.md raises `hub_skill_no_skill_md`.
    - 101 files raise `hub_too_many_files`.
    - A file of 1 MiB + 1 byte raises `hub_skill_too_large`.
- [ ] **Step 2: Run** `uv run pytest tests/hub/test_rules.py -q`. Expected: FAIL (import error, module missing).
- [ ] **Step 3: Implement** the models, schemas and rules as listed in Interfaces. Add the `app.hub` import to
  `app/models.py`, then add the org column.
- [ ] **Step 4: Run** `uv run pytest tests/hub/test_rules.py -q`. Expected: PASS.
- [ ] **Step 5: Generate the migration** against `megoo_migrate` (`"tool hub"`). Name every constraint explicitly,
  then run `alembic downgrade -1 && alembic upgrade head` there. Then run
  `uv run pytest tests/core/test_migrations.py -q`. Expected: PASS (models match migrations).
- [ ] **Step 6: Commit** `feat(hub): tool, share and file models; rules for names, secrets and skill files`.

### Task 2: My MCP tools: create, read, edit, delete, secrets

**Files:**
- Create: `backend/app/hub/service.py`, `backend/app/hub/router.py`
- Modify: `backend/app/main.py` (register `hub_router`)
- Test: `backend/tests/hub/test_mcp_tools.py`

**Interfaces:**
- Consumes: the Task 1 models, schemas and rules.
- Produces (schemas):
  - `ToolIn(kind: Literal["mcp"], name, description = "", spec: McpSpec, read_only_safe = False)`
  - `ToolPatch(name?, description?, spec?, read_only_safe?)`
  - `SecretsIn(values: dict[str, str])`: an empty string clears that slot
  - `SecretSlot(name, set: bool)`
  - `ToolSummary`, with fields:
    - `id, kind, name, description, version`
    - `owner: {id, name}`
    - `is_copy`
    - `source_state: Literal["ok","update_available","no_longer_shared"] | None`
    - `removed: bool`
    - `secrets_missing: bool`: owner only, otherwise false
    - `runs_code: bool`
    - `read_only_safe`
    - `sharing: Sharing | None`: owner only
  - `Sharing(teams: list[{id,name}], users: list[{id,name}], everyone: bool)`
  - `ToolOut(ToolSummary)`, adding:
    - `spec: McpSpec | None`: secret values always `""`
    - `secrets: list[SecretSlot]`
    - `files: list[{path, size, runs_on: list[str] | None}] | None`
    - `source: {id, name, owner_name, version} | None`
    - `flagged: list[str]`
    - `can_edit: bool`
- Produces (service):
  - `get_tool_or_404(db, tool_id) -> HubTool`
  - `can_view(db, user, tool) -> bool`. The rules: the owner always; anyone else only if the tool isn't removed and
    either a share row names one of their current teams or them, or `share_everyone` is set and the org setting is on;
    an admin also sees any tool that is shared beyond "only me".
  - `require_owner(user, tool) -> None`: raises a 404 for a viewer who can't see the tool, and a 403 `forbidden` for
    one who can see it but isn't the owner.
  - `read_secrets(tool) -> dict[str, str]`: internal only, never routed in this plan
  - `write_secrets(tool, values) -> None`
  - `tool_out(db, user, tool) -> ToolOut`
- Produces (routes, `router = APIRouter(prefix="/api/hub", tags=["hub"])`):
  - `POST /tools` returns 201 `ToolOut`, and 409 `hub_name_taken`.
  - `GET /tools/{id}` returns `ToolOut`, and 404 when the viewer can't view it.
  - `PATCH /tools/{id}` is owner only. On a copy, only `read_only_safe` may change; anything else is 409
    `hub_copy_read_only`. On a removed tool it is 409 `hub_removed`.
  - `PUT /tools/{id}/secrets` is owner only. Unknown slot names are 422 `hub_unknown_secret`; add that code to
    `MESSAGES` as "That secret isn't part of this tool."
  - `DELETE /tools/{id}` is owner only and returns 204.
- A spec change that removes a secret slot drops its stored value. The secret values sent in `spec` are ignored, since
  values are set only through `/secrets`.

- [ ] **Step 1: Write the failing tests** (`_as(client, db, role)` helper as in `tests/teams/test_teams.py`):
  - `test_create_and_read_mcp`: POST an http tool with header `Authorization` secret and
    `PUT /secrets {"values":{"Authorization":"Bearer sk-live-abcdef123456"}}`. Then the GET body's `secrets` is
    `[{"name":"Authorization","set":true}]`, and `"sk-live-abcdef123456"` is not in `resp.text`, both for the GET and
    for the PUT response.
  - `test_secret_value_in_spec_is_ignored`: a POST whose spec header has `secret:true, value:"sk-xyz12345678"` stores
    no value (`set` false), and the value is not in `resp.text`.
  - `test_duplicate_name_409`.
  - `test_other_user_cannot_see_private_tool`: the GET returns 404.
  - `test_patch_bumps_version_and_rev`: a spec change bumps both `version` and `rev`. A secrets PUT bumps `rev` only.
    A `read_only_safe` change bumps `rev` only.
  - `test_removing_slot_drops_value`: PATCH a spec without the secret header, then add it back; `set` is false.
  - `test_unknown_secret_422`.
  - `test_secrets_encrypted_at_rest`: the raw `secrets_enc` column (read via `db`) does not contain the plain value.
- [ ] **Step 2: Run** `uv run pytest tests/hub/test_mcp_tools.py -q`. Expected: FAIL (404 for the routes).
- [ ] **Step 3: Implement** the service and router. Store secrets as `encrypt(json.dumps(values))`. Register the router
  in `app/main.py`.
- [ ] **Step 4: Run** `uv run pytest tests/hub -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(hub): my MCP tools with encrypted secrets`.

### Task 3: Skills: upload, replace, read files

**Files:**
- Modify: `backend/app/hub/router.py`, `backend/app/hub/service.py`
- Test: `backend/tests/hub/test_skills.py`

**Interfaces:**
- Consumes: `normalize_skill_files`, `skill_frontmatter`, `script_systems` and `tool_out`.
- Produces (routes):
  - `POST /api/hub/skills` (multipart) returns 201 `ToolOut`. The fields are either one `file` ending in `.zip`, or
    several `files` whose filenames are relative paths (as a browser folder picker sends them). The name and
    description come from the SKILL.md frontmatter. A missing or invalid name is 422 `hub_bad_name`.
  - `PUT /api/hub/tools/{id}/files` (multipart, the same two forms) replaces all files. It is owner only, not for
    copies (409 `hub_copy_read_only`), and bumps `version` and `rev`. The name stays; the description updates from the
    frontmatter when one is present.
  - `GET /api/hub/tools/{id}/file?path=` returns `{path, size, text: str | None}` for viewers. `text` is `None` when
    the bytes aren't UTF-8. An unknown path is 404.
- Zip reading uses stdlib `zipfile`. Directory entries are skipped. The sizes in the zip header are checked before
  reading, so the server never decompresses past 2 MiB.

- [ ] **Step 1: Write the failing tests:**
  - `test_upload_zip_creates_skill`: a zip with `ui-review/SKILL.md` (with frontmatter) and
    `ui-review/scripts/contrast.py` gives `name == "ui-review"`, and `files` holds `SKILL.md` and `scripts/contrast.py`
    with `runs_on == ["linux","macos","windows"]` for the script. `runs_code` is true.
  - `test_upload_folder_files`: the same content sent as two `files` parts gives the same result.
  - `test_bad_paths_refused`: a zip containing `../evil.md` gives 422 `hub_bad_path`.
  - `test_zip_bomb_refused`: a zip whose single entry has a declared size of 3 MiB gives 413 `hub_skill_too_large`.
    Build it with `zipfile` compressing 3 MiB of zeros.
  - `test_replace_files_bumps_version`.
  - `test_read_file_text_and_binary`: SKILL.md returns text; a PNG byte string returns `text is None`.
- [ ] **Step 2: Run** `uv run pytest tests/hub/test_skills.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the routes as listed in Interfaces.
- [ ] **Step 4: Run** `uv run pytest tests/hub -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(hub): skills uploaded as a zip or folder, with script flags`.

### Task 4: Sharing and the three shelves

**Files:**
- Modify: `backend/app/hub/router.py`, `backend/app/hub/service.py`, `backend/app/org/router.py` (settings In/Out
  nested `hub: HubSettings{share_everyone: bool}`)
- Test: `backend/tests/hub/test_sharing.py`, `backend/tests/org/` (extend the existing settings test file with the
  `hub` block)

**Interfaces:**
- Produces (routes):
  - `PUT /api/hub/tools/{id}/sharing`, with body `SharingIn(teams: list[UUID], users: list[UUID], everyone: bool)`,
    returns `ToolOut`. It is owner only, and these are refused:
    - a copy: 409 `hub_copy_read_only`;
    - a removed tool: 409 `hub_removed`;
    - an MCP tool whose `flagged_values` is non-empty while any target is given: 409 `hub_flagged_values`;
    - `everyone` while the org setting is off: 409 `hub_everyone_off`;
    - a team the user isn't a member of, unless they're an admin: 403 `hub_team_not_member`;
    - an inactive user or themselves: 422 `hub_bad_user`, added to `MESSAGES` as "You can't share with that person."

    It replaces all share rows. When the targets changed, it records `hub.tool_shared` with
    `data={name, teams, users, everyone}`.
  - `GET /api/hub/tools?shelf=mine|shared|everyone&q=` returns `list[ToolSummary]`, ordered by name.
    - `mine` is everything owned, removed tools included.
    - `shared` is tools not owned, not removed, and shared to the user's current teams or to the user.
    - `everyone` is tools not owned, not removed, with `share_everyone` set; it is empty when the org setting is off.
    - `q` is a case-insensitive match on name or description.
  - `GET` and `PUT /api/admin/settings` carry `hub.share_everyone`.

- [ ] **Step 1: Write the failing tests:**
  - `test_share_with_team_shows_on_shared_shelf`: a team member sees the tool; a non-member doesn't. A GET by the
    member returns `secrets[].set == false` and `sharing is None`.
  - `test_left_team_loses_access`: remove the member from the team. The shelf no longer lists the tool, and the GET is
    404.
  - `test_share_with_person_and_everyone`.
  - `test_everyone_off_hides_and_refuses`: the admin turns it off. The `everyone` shelf is `[]`, and sharing with
    `everyone:true` is 409 `hub_everyone_off`. Turning it back on shows the earlier share again.
  - `test_flagged_values_block_sharing`: an arg `sk-live1234567890` gives 409. PATCH with
    `acknowledged:["args[1]"]`, and sharing works.
  - `test_share_with_non_member_team_403` and `test_share_with_self_422`.
  - `test_share_audited`: the audit row has `action == "hub.tool_shared"`, and its `data` holds no spec values.
  - `test_admin_settings_hub_block`: the GET returns `hub.share_everyone == true`. A PUT without a `hub` block keeps
    it.
- [ ] **Step 2: Run** `uv run pytest tests/hub/test_sharing.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the routes as listed in Interfaces. Visibility uses `user_team_ids(db, user.id)` at read
  time.
- [ ] **Step 4: Run** `uv run pytest tests/hub tests/org -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(hub): share with teams, people or everyone; three shelves`.

### Task 5: Copies: add to my library, take update, make it my own

**Files:**
- Modify: `backend/app/hub/router.py`, `backend/app/hub/service.py`
- Test: `backend/tests/hub/test_copies.py`

**Interfaces:**
- Produces (routes):
  - `POST /api/hub/tools/{id}/copy` returns 201 `ToolOut` (the new copy). The viewer must be able to see the tool and
    must not own it. These are refused:
    - a removed tool: 409 `hub_removed`;
    - an existing live copy of the same source: 409 `hub_already_copied`;
    - a name clash with one of their tools: 409 `hub_name_taken`.

    The copy has `is_copy=True`, `source_id`, `source_version = source.version`, the spec with the secrets left blank,
    copied files, `read_only_safe=False`, no shares, and `version = source.version`.
  - `POST /api/hub/tools/{id}/update` (on the copy, owner only) returns `ToolOut`. Only copies are allowed, and these
    are refused:
    - a source that isn't visible: 409 `hub_no_update`;
    - a source not newer: 409 `hub_no_update`;
    - a removed copy: 409 `hub_removed`.

    It replaces the spec, files and description, keeps the stored secrets for slot names that still exist, and bumps
    `rev`.
  - `POST /api/hub/tools/{id}/own` returns `ToolOut`. On a copy it sets `is_copy=False` and `source_id=None`, and bumps
    `rev`. A removed copy is 409 `hub_removed`.
  - `source_state` on summaries and detail:
    - `None` when it isn't a copy;
    - `"no_longer_shared"` when the source is deleted or not visible to the owner;
    - `"update_available"` when the source's version is newer;
    - `"ok"` otherwise.

- [ ] **Step 1: Write the failing tests:**
  - `test_copy_has_no_secrets`: the source has a secret set. The copy's `secrets[].set` is false, and the source's
    value is not in `resp.text`.
  - `test_copy_twice_409`.
  - `test_update_available_then_take`: the source's PATCH bumps the version. The copy's state is `update_available`.
    After `/update` it's `ok`, and the version matches.
  - `test_update_keeps_secrets_for_surviving_slots`: the copy sets `API_KEY`. The source renames its slot to `TOKEN`
    and keeps `API_KEY`. After the update, `API_KEY` is `set:true`, `TOKEN` is `set:false`, and `secrets_missing` is
    true.
  - `test_unshared_source_shows_no_longer_shared`. Deleting the source gives the same state.
  - `test_copy_edits_refused_until_owned`: a PATCH of the description on a copy is 409 `hub_copy_read_only`. After
    `/own`, the PATCH works and `is_copy` is false.
- [ ] **Step 2: Run** `uv run pytest tests/hub/test_copies.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the routes as listed in Interfaces.
- [ ] **Step 4: Run** `uv run pytest tests/hub -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(hub): copies — add to my library, take updates, make it my own`.

### Task 6: Admin: shared tools, stop sharing, remove

**Files:**
- Create: `backend/app/hub/admin_router.py` (`admin_router = APIRouter(prefix="/api/admin/hub", tags=["admin"])`)
- Modify: `backend/app/main.py`
- Test: `backend/tests/hub/test_admin.py`

**Interfaces:**
- Produces (routes, all `AdminUser`):
  - `GET /api/admin/hub/tools?q=` returns `list[AdminToolOut]`, where `AdminToolOut` is `ToolSummary` plus
    `sharing: Sharing`. It lists tools with any share row or `share_everyone`, not removed. Private tools never appear.
  - `POST /api/admin/hub/tools/{id}/unshare` returns 204. It deletes the share rows, sets `share_everyone=False`, and
    records `hub.tool_unshared`.
  - `POST /api/admin/hub/tools/{id}/remove` returns 204. It unshares the tool, sets `removed_at` and `removed_by_id` on
    it and on every **live copy** (`source_id == id and is_copy`), bumps `rev` on each, and records `hub.tool_removed`.
- Removed tools: the owner still sees them on `mine` with `removed: true`. Every edit, share, copy, update or own on a
  removed tool is 409 `hub_removed`, and DELETE still works.

- [ ] **Step 1: Write the failing tests:**
  - `test_admin_list_only_shared`: a private tool isn't listed; a team-shared one is.
  - `test_member_forbidden`: a member gets 403 on all three routes.
  - `test_unshare`: after unsharing, the team member no longer sees the tool, and an audit row exists.
  - `test_remove_marks_live_copies_only`: user B has a live copy, and user C made a copy their own before the removal.
    After the removal, the source and B's copy are `removed:true`, and C's tool is untouched. B's PATCH of
    `read_only_safe` is 409 `hub_removed`, and B's DELETE is 204.
  - `test_removed_hidden_from_shelves`.
- [ ] **Step 2: Run** `uv run pytest tests/hub/test_admin.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the admin router as listed in Interfaces.
- [ ] **Step 4: Run** the whole backend suite with `uv run pytest -q`, plus ruff on `app/hub tests/hub`. Expected: all
  pass.
- [ ] **Step 5: Commit** `feat(hub): admins see shared tools, stop sharing, remove`.

### Task 7: Frontend: data module, sidebar, trail, the hub page

**Files:**
- Create: `frontend/src/lib/hub.ts`, `frontend/src/app/(app)/hub/page.tsx`, `frontend/src/components/hub/ToolRow.tsx`
- Modify: `frontend/src/lib/api-types.ts` (via `npm run gen:api`), `frontend/src/lib/errors.ts`,
  `frontend/src/components/shell/Sidebar.tsx`, `frontend/src/lib/trail.ts`
- Test: `frontend/src/app/(app)/hub/__tests__/HubPage.test.tsx`, `frontend/src/lib/__tests__/trail.test.tsx` (extend)

**Interfaces:**
- Produces (`lib/hub.ts`):
  - `hubKeys` (all keys start with `"hub"`): `all`, `shelf(shelf, q)`, `tool(id)`, `file(id, path)`, `admin(q)`
  - types `HubTool = S["ToolOut"]`, `HubToolSummary = S["ToolSummary"]`, `HubShelf = "mine"|"shared"|"everyone"`
  - hooks `useHubShelf(shelf, q)`, `useHubTool(id)`, `useHubFile(id, path | null)`
- Sidebar:
  - the item `{ href: "/hub", label: "Tool Hub", icon: Blocks }` (lucide `Blocks`) goes right after Memory in `MAIN`;
  - the admin item `{ href: "/admin/hub", label: "Tool Hub", icon: Blocks }` goes after Agents in `ADMIN`.
- Trail:
  - `SECTIONS.hub = "Tool Hub"`;
  - `UNDER.hub = { "new-mcp": "Add MCP", "new-skill": "Add skill" }`;
  - `UNDER.admin.hub = "Tool Hub"`.
- The page: `PageHeader` with title "Tool Hub", the subtitle "MCP servers and skills you keep once and push to your
  machines. Keys stay with you; sharing never sends them.", and the actions `Add skill` (link to `/hub/new-skill`) and
  `Add MCP` (link to `/hub/new-mcp`).
- `Tabs` uses `useTabParam(["mine","shared","everyone"])`. A search input (`type="search"`, accessible name `Search
  tools`) feeds `q`.
- `ToolRow` links to `/hub/{id}`. It shows:
  - the name;
  - a Badge `MCP` (cyan) or `Skill` (pink);
  - the description;
  - on `mine`: `key missing` (amber) when `secrets_missing`, `Update available` (cyan) or `no longer shared` (muted)
    from `source_state`, `removed by an admin` (pink) when removed, and a sharing summary (`Private`, `Shared: <team
    names>`, `Everyone`);
  - on the other shelves: `by <owner name>`.
- Empty states: `Nothing here yet.` on `mine`, and `Nothing shared with you yet.` on the others.

- [ ] **Step 1: Run** `npm run gen:api`. Add the error codes from Global Constraints to `MESSAGES`.
- [ ] **Step 2: Write the failing tests:**
  - `HubPage.test.tsx`, with fetch stubbed per URL:
    - the `Mine` tab lists two rows;
    - the row with `secrets_missing` shows `key missing`;
    - clicking `Shared with me` fetches `/api/hub/tools?shelf=shared`;
    - typing in `Search tools` refetches with `q=`;
    - the empty shelf shows the empty text.
  - `trail.test.tsx`: `pathTrail("/hub/new-mcp")` gives `[{label:"Tool Hub",href:"/hub"},{label:"Add MCP"}]`, and
    `pathTrail("/admin/hub")` gives `[{label:"Admin"},{label:"Tool Hub"}]`.
- [ ] **Step 3: Run** `npx vitest run src/app/(app)/hub src/lib/__tests__/trail.test.tsx`. Expected: FAIL.
- [ ] **Step 4: Implement** the data module, sidebar, trail and page as listed in Interfaces.
- [ ] **Step 5: Run** the same tests, then `npx eslint src` and `npx tsc --noEmit`. Expected: PASS and clean.
- [ ] **Step 6: Commit** `feat(hub): Tool Hub page with Mine, Shared with me and Everyone`.

### Task 8: Frontend: add and edit an MCP, secrets, sharing

**Files:**
- Create: `frontend/src/app/(app)/hub/new-mcp/page.tsx`, `frontend/src/app/(app)/hub/[id]/page.tsx`,
  `frontend/src/components/hub/McpForm.tsx`, `frontend/src/components/hub/EntriesEditor.tsx`,
  `frontend/src/components/hub/SecretsForm.tsx`, `frontend/src/components/hub/ShareEditor.tsx`
- Test: `frontend/src/components/hub/__tests__/McpForm.test.tsx`, `frontend/src/components/hub/__tests__/ShareEditor.test.tsx`,
  `frontend/src/app/(app)/hub/__tests__/ToolPage.test.tsx`

**Interfaces:**
- **`McpForm({initial?, onSubmit(body)})`**:
  - Fields: `Name`, `Description`, `Kind` (Select: `Web address` = http, `Command` = stdio), `Address` (http) or
    `Command` + `Arguments` (one per line, stdio), plus an `Other systems` disclosure with an optional Command and
    Arguments per `Windows`, `Linux` and `macOS`.
  - `Headers` (http) or `Environment` (stdio) through `EntriesEditor`: rows of name, value and a checkbox named
    `Secret`. A secret row's value input is `type="password"` with the placeholder `Set below after saving`, and is
    disabled.
  - The `Safe in read-only runs` checkbox, with its help text.
  - A live preview `What others get`: the setup with secret values shown as `‹their own›`.
- **`SecretsForm({tool})`**: one password input per slot, labelled with the slot name and showing `set` / `not set`.
  Saving calls `PUT /api/hub/tools/{id}/secrets` with only the fields that were typed in.
- **`ShareEditor({tool})`**:
  - `Only me` / `Teams` (multi-pick from `GET /api/teams`, filtered to `is_member`, or all for admins) / `People`
    (search `GET /api/users?q=`, excluding self) / `Everyone on MegooColab`.
  - It shows `flagged` as a list, each item with a `Not a secret` button. That button PATCHes `spec.acknowledged`.
  - Save calls `PUT …/sharing`.
- **`/hub/new-mcp`**: posts, then routes to `/hub/{id}`.
- **`/hub/[id]`** (owner, MCP):
  - header: name, badges, Delete (through `useConfirm`, danger);
  - sections: `Setup` (`McpForm` in edit mode), `Secrets`, `Sharing`;
  - trail: `[{Tool Hub,/hub},{name}]`.

- [ ] **Step 1: Write the failing tests:**
  - McpForm: choosing `Command` shows `Command` and `Arguments`. Submitting builds
    `{transport:"stdio", command:{command:"npx", args:["-y","@upstash/context7-mcp"]}}`. A secret env row submits
    `value:""`.
  - ShareEditor: when `flagged` is non-empty, the `Share` button is disabled and `Not a secret` PATCHes
    `acknowledged`. A 409 `hub_everyone_off` shows its message.
  - ToolPage: the owner view shows the three sections. Typing a secret and saving sends only that key.
- [ ] **Step 2: Run** `npx vitest run src/components/hub src/app/(app)/hub`. Expected: FAIL.
- [ ] **Step 3: Implement** the components and pages as listed in Interfaces.
- [ ] **Step 4: Run** the same tests, then eslint and tsc. Expected: PASS and clean.
- [ ] **Step 5: Commit** `feat(hub): add and edit an MCP, its secrets and who it's shared with`.

### Task 9: Frontend: skills, and viewing what others share

**Files:**
- Create: `frontend/src/app/(app)/hub/new-skill/page.tsx`, `frontend/src/components/hub/SkillUpload.tsx`,
  `frontend/src/components/hub/SkillFiles.tsx`, `frontend/src/components/hub/SharedToolView.tsx`
- Modify: `frontend/src/app/(app)/hub/[id]/page.tsx`
- Test: `frontend/src/components/hub/__tests__/SkillUpload.test.tsx`, `frontend/src/components/hub/__tests__/SharedToolView.test.tsx`

**Interfaces:**
- **`SkillUpload({toolId?, onDone(tool)})`**: two buttons, `Upload a .zip` (`input type=file accept=".zip"`) and
  `Upload a folder` (`input type=file` with the `webkitdirectory` attribute). The folder upload sends each file as
  `files` with `webkitRelativePath` as its filename. With `toolId`, it PUTs to `/files`; otherwise it POSTs to
  `/api/hub/skills`.
- **`SkillFiles({tool})`**: a file list with sizes, where a script shows `runs code`. Clicking a file shows its text
  (from `useHubFile`) in a `<pre>`, or `Can't show this file.` when `text` is null.
- **`SharedToolView({tool})`**, the view for anyone who isn't the owner:
  - `by <owner name>`;
  - for an MCP, the setup read-only, with secret slots listed as `needs <NAME>`;
  - for a skill, `SkillFiles`;
  - when `runs_code` or the tool is a stdio MCP, the script warning copy plus the script paths;
  - the button `Add to my library` (POST `/copy`, then route to the new id).
- **The owner's view of a copy**:
  - a source line `Copy of <name> by <owner> · v<n>`;
  - `Take update` when `source_state=="update_available"`;
  - `Make it my own` (through `useConfirm`: "It stops getting updates from <owner>.");
  - Secrets and the `Safe in read-only runs` checkbox stay editable; Setup, Files and Sharing are read-only.
- **The owner's view of a removed tool**: the banner `removed by an admin` and only Delete.

- [ ] **Step 1: Write the failing tests:**
  - SkillUpload: a folder upload sends `FormData` whose `files` entries carry their relative paths. A 422
    `hub_skill_no_skill_md` shows its message.
  - SharedToolView: a skill with a `.sh` file shows the warning and the path. `Add to my library` POSTs `/copy`. A
    stdio MCP shows `needs API_KEY`.
- [ ] **Step 2: Run** `npx vitest run src/components/hub`. Expected: FAIL.
- [ ] **Step 3: Implement** the components as listed in Interfaces, and wire them into `/hub/[id]` by `can_edit`,
  `is_copy`, `removed` and `kind`.
- [ ] **Step 4: Run** `npx vitest run src`, then eslint and tsc. Expected: PASS and clean.
- [ ] **Step 5: Commit** `feat(hub): skills, and a careful look before taking someone's tool`.

### Task 10: Frontend: admin page and the Everyone setting

**Files:**
- Create: `frontend/src/app/(app)/admin/hub/page.tsx`
- Modify: `frontend/src/app/(app)/admin/settings/page.tsx` (adds a `Tool Hub` section with the checkbox `Let people
  share tools with everyone`)
- Test: `frontend/src/app/(app)/admin/hub/__tests__/AdminHub.test.tsx`, plus the existing admin settings test file

**Interfaces:**
- `/admin/hub`: `usePageTitle("Tool Hub", "Admin")` with the same non-admin guard as `admin/git`. It has a search box
  and a list of shared tools showing owner, kind and who it's shared with, plus two buttons per tool:
  - `Stop sharing` (warn confirm);
  - `Remove` (danger confirm, with the text "Everyone who added it sees “removed by an admin”. Nothing changes on their
    machines until they push.").

- [ ] **Step 1: Write the failing tests:**
  - Remove: after the confirm, it POSTs `/api/admin/hub/tools/{id}/remove`, and the list refetches.
  - A non-admin sees the permission card.
  - The settings checkbox PUTs `hub: {share_everyone: false}`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** the page and the settings section as listed in Interfaces.
- [ ] **Step 4: Run** `npx vitest run src`, then eslint and tsc. Expected: PASS and clean.
- [ ] **Step 5: Commit** `feat(hub): admin view of shared tools`.

### Task 11: End to end

**Files:**
- Create: `frontend/e2e/hub.spec.ts`

- [ ] **Step 1: Write the spec** `tool hub: add, share without the key, take a copy`, as two users with
  `setupOrSignIn`, the admin and a second user created through the admin API, both in a new team:
  1. User A adds an MCP `ctx-e2e` (http, a secret header `X-Key`), sets its secret to `e2e-secret-value-123456`, and
     shares it with the team.
  2. User B opens `Shared with me`, sees `ctx-e2e`, opens it, sees `needs X-Key`, and asserts the page text doesn't
     contain `e2e-secret-value-123456`. B adds it to their library, sees `key missing` on `Mine`, and A updates the
     description.
  3. B sees `Update available`, and takes it.
  4. The admin opens `/admin/hub` and removes `ctx-e2e`. B's `Mine` shows `removed by an admin`.
- [ ] **Step 2: Run** with the `megoo-e2e` stack (`up -d --build --wait`, then
  `cd frontend && npx playwright test e2e/hub.spec.ts`, then the full suite). Then bring it down with `down -v`.
  Expected: all pass.
- [ ] **Step 3: Commit** `test(e2e): Tool Hub sharing without keys`.
