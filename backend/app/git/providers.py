"""Read-only clients for git hosts (GIT-1, GIT-3): who am I, and the state of one pull request.

The token comes from the connection, is decrypted only to build the request, and never appears in a URL, a log
line or an error: a failure is a short code (GitProviderError.code). Redirects are never followed, so a token
cannot be sent on to another host.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from app.core.crypto import decrypt
from app.git.models import GitConnection, GitKind

TIMEOUT = 10.0
GITHUB_API_VERSION = "2022-11-28"
_NUMBER = r"([1-9][0-9]{0,8})"
_SEG = r"[A-Za-z0-9_.\-]+"
_PR_PATHS = {
    GitKind.github: re.compile(rf"^({_SEG}/{_SEG})/pull/{_NUMBER}$"),
    GitKind.gitlab: re.compile(rf"^({_SEG}(?:/{_SEG})+)/-/merge_requests/{_NUMBER}$"),
    GitKind.gitea: re.compile(rf"^({_SEG}/{_SEG})/pulls/{_NUMBER}$"),
}
_SCP = re.compile(r"^[A-Za-z0-9_.\-]+@[A-Za-z0-9_.\-]+:(.+)$")
_RUN_FAILED = {"failure", "cancelled", "timed_out", "action_required", "startup_failure", "stale"}


class GitProviderError(Exception):
    """A provider call failed: unauthorized | forbidden | not_found | unreachable | rate_limited | bad_response.
    forbidden: the token is valid but may not do this (managing webhooks without the permission)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PrRef:
    kind: str
    web_base: str
    path: str  # owner/repo, or a nested GitLab group path
    number: int


@dataclass(frozen=True)
class PrStatus:
    state: str  # open | merged | closed
    checks: str  # success | failure | pending | none
    review: str  # approved | changes_requested | none
    merged_at: datetime | None
    head_sha: str | None
    head_branch: str | None = None  # the pull request's source branch, to check it is the task's


# ---- URLs ------------------------------------------------------------------------------------


def _base(url: str) -> tuple[str, str, str]:
    parts = urlsplit(url)
    return parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/")


def parse_pr_url(url: str, conn: GitConnection) -> PrRef | None:
    """The pull request a URL names on this connection's host, or None. The URL must be the pull request page
    itself (no extra path, query or fragment) under the connection's base URL."""
    if not isinstance(url, str) or not url:
        return None
    parts = urlsplit(url.strip())
    scheme, netloc, prefix = _base(conn.base_url)
    if parts.scheme.lower() != scheme or parts.netloc.lower() != netloc or parts.query or parts.fragment:
        return None
    path = parts.path
    if prefix:
        if not path.startswith(prefix + "/"):
            return None
        path = path[len(prefix):]
    m = _PR_PATHS[GitKind(conn.kind)].match(path.strip("/"))
    if m is None:
        return None
    return PrRef(str(conn.kind), conn.base_url, m.group(1), int(m.group(2)))


def repo_path(repo_url: str) -> str | None:
    """owner/repo (or a nested group path) of a repository URL in https, ssh or scp form, without .git."""
    if not isinstance(repo_url, str):
        return None
    raw = repo_url.strip()
    m = _SCP.match(raw)
    if m and "://" not in raw:
        path = m.group(1)
    else:
        parts = urlsplit(raw)
        if parts.scheme not in ("http", "https", "ssh") or not parts.netloc:
            return None
        path = parts.path
    path = path.strip("/")
    path = path.removesuffix(".git")
    return path if "/" in path else None


# the hosted services: a connection to one needs no address of its own
HOSTED: dict[GitKind, str] = {GitKind.github: "https://github.com", GitKind.gitlab: "https://gitlab.com"}


def is_hosted(conn: GitConnection) -> bool:
    return HOSTED.get(GitKind(conn.kind)) == conn.base_url.rstrip("/").lower()


def api_base(conn: GitConnection) -> str:
    kind = GitKind(conn.kind)
    if kind == GitKind.github:
        return "https://api.github.com" if urlsplit(conn.base_url).netloc.lower() == "github.com" else f"{conn.base_url}/api/v3"
    if kind == GitKind.gitlab:
        return f"{conn.base_url}/api/v4"
    return f"{conn.base_url}/api/v1"


def _headers(conn: GitConnection) -> dict[str, str]:
    try:
        token = decrypt(conn.token_enc)
    except Exception:  # noqa: BLE001 - SECRET_KEY changed since the token was saved
        raise GitProviderError("bad_token") from None
    if not token.isascii() or not token.isprintable():
        raise GitProviderError("bad_token")  # not sendable in an HTTP header
    kind = GitKind(conn.kind)
    if kind == GitKind.github:
        return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": GITHUB_API_VERSION}
    if kind == GitKind.gitlab:
        return {"PRIVATE-TOKEN": token}
    return {"Authorization": f"token {token}"}


# ---- HTTP ------------------------------------------------------------------------------------


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False)


async def _send(
    client: httpx.AsyncClient, conn: GitConnection, method: str, path: str, *, params: dict | None = None,
    json: Any = None, ok: tuple[int, ...] = (200,),
) -> Any:
    try:
        r = await client.request(method, api_base(conn) + path, headers=_headers(conn), params=params, json=json)
    except httpx.HTTPError:
        raise GitProviderError("unreachable") from None
    if r.status_code == 401:
        raise GitProviderError("unauthorized")
    if r.status_code == 404:
        raise GitProviderError("not_found")
    if r.status_code == 429 or (r.status_code == 403 and r.headers.get("X-RateLimit-Remaining") == "0"):
        raise GitProviderError("rate_limited")
    if r.status_code == 403:
        raise GitProviderError("forbidden")
    if r.status_code not in ok:
        raise GitProviderError("bad_response")
    if r.status_code == 204 or not r.content:
        return None
    try:
        return r.json()
    except ValueError:
        raise GitProviderError("bad_response") from None


async def _get(client: httpx.AsyncClient, conn: GitConnection, path: str, params: dict | None = None) -> Any:
    return await _send(client, conn, "GET", path, params=params)


async def _optional(client: httpx.AsyncClient, conn: GitConnection, path: str) -> Any:
    """An extra the provider may not offer (GitLab CE approvals): missing means none, other errors stand."""
    try:
        return await _get(client, conn, path)
    except GitProviderError as e:
        if e.code == "not_found":
            return None
        raise


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _combine(*states: str) -> str:
    if "failure" in states:
        return "failure"
    if "pending" in states:
        return "pending"
    return "success" if "success" in states else "none"


def _combined_status(data: Any) -> str:
    """GitHub/Gitea combined commit status; no statuses at all is none."""
    if not isinstance(data, dict):
        raise GitProviderError("bad_response")
    if not data.get("total_count"):
        return "none"
    state = data.get("state")
    if state in ("failure", "error"):
        return "failure"
    return "success" if state == "success" else "pending"


def _check_runs(data: Any) -> str:
    runs = data.get("check_runs") if isinstance(data, dict) else None
    if not isinstance(runs, list):
        raise GitProviderError("bad_response")
    states = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        if run.get("status") != "completed":
            states.append("pending")
        else:
            states.append("failure" if run.get("conclusion") in _RUN_FAILED else "success")
    return _combine(*states)


def _reviews(data: Any) -> str:
    """The latest decisive review of each reviewer: any change request wins over approvals."""
    if not isinstance(data, list):
        raise GitProviderError("bad_response")
    latest: dict[str, str] = {}
    for review in data:
        if not isinstance(review, dict):
            continue
        state = str(review.get("state") or "").upper()
        login = str((review.get("user") or {}).get("login") or "")
        if state in ("APPROVED", "CHANGES_REQUESTED", "REQUEST_CHANGES"):
            latest[login] = state
    if any(s in ("CHANGES_REQUESTED", "REQUEST_CHANGES") for s in latest.values()):
        return "changes_requested"
    return "approved" if latest else "none"


def _pr_fields(pr: Any) -> tuple[str, datetime | None, str | None, str | None]:
    if not isinstance(pr, dict) or pr.get("state") not in ("open", "closed"):
        raise GitProviderError("bad_response")
    head = pr.get("head") if isinstance(pr.get("head"), dict) else {}
    sha, ref = head.get("sha"), head.get("ref")
    state = "merged" if pr.get("merged") is True else pr["state"]
    return (state, _time(pr.get("merged_at")), sha if isinstance(sha, str) else None,
            ref if isinstance(ref, str) else None)


async def _github(client, conn: GitConnection, ref: PrRef) -> PrStatus:
    base = f"/repos/{ref.path}"
    state, merged_at, sha, branch = _pr_fields(await _get(client, conn, f"{base}/pulls/{ref.number}"))
    checks = "none"
    if sha:
        checks = _combine(_combined_status(await _get(client, conn, f"{base}/commits/{sha}/status")),
                          _check_runs(await _get(client, conn, f"{base}/commits/{sha}/check-runs")))
    review = _reviews(await _get(client, conn, f"{base}/pulls/{ref.number}/reviews"))
    return PrStatus(state, checks, review, merged_at, sha, branch)


async def _gitea(client, conn: GitConnection, ref: PrRef) -> PrStatus:
    base = f"/repos/{ref.path}"
    state, merged_at, sha, branch = _pr_fields(await _get(client, conn, f"{base}/pulls/{ref.number}"))
    checks = _combined_status(await _get(client, conn, f"{base}/commits/{sha}/status")) if sha else "none"
    review = _reviews(await _get(client, conn, f"{base}/pulls/{ref.number}/reviews"))
    return PrStatus(state, checks, review, merged_at, sha, branch)


_GITLAB_STATES = {"opened": "open", "merged": "merged", "closed": "closed", "locked": "closed"}


async def _gitlab(client, conn: GitConnection, ref: PrRef) -> PrStatus:
    mr_path = f"/projects/{quote(ref.path, safe='')}/merge_requests/{ref.number}"
    mr = await _get(client, conn, mr_path)
    if not isinstance(mr, dict) or mr.get("state") not in _GITLAB_STATES:
        raise GitProviderError("bad_response")
    pipeline = mr.get("head_pipeline")
    status = pipeline.get("status") if isinstance(pipeline, dict) else None
    if status is None or status == "skipped":
        checks = "none"
    elif status == "success":
        checks = "success"
    elif status in ("failed", "canceled"):
        checks = "failure"
    else:
        checks = "pending"
    approvals = await _optional(client, conn, f"{mr_path}/approvals")
    review = "approved" if isinstance(approvals, dict) and approvals.get("approved") is True else "none"
    sha, branch = mr.get("sha"), mr.get("source_branch")
    return PrStatus(_GITLAB_STATES[mr["state"]], checks, review, _time(mr.get("merged_at")),
                    sha if isinstance(sha, str) else None, branch if isinstance(branch, str) else None)


async def fetch_pr(conn: GitConnection, ref: PrRef, *, client: httpx.AsyncClient | None = None) -> PrStatus:
    """The pull request's state, checks and review, read with the connection's token."""
    own = client is None
    client = client or _client()
    try:
        kind = GitKind(conn.kind)
        if kind == GitKind.github:
            return await _github(client, conn, ref)
        if kind == GitKind.gitlab:
            return await _gitlab(client, conn, ref)
        return await _gitea(client, conn, ref)
    except (KeyError, TypeError, AttributeError):
        raise GitProviderError("bad_response") from None
    finally:
        if own:
            await client.aclose()


async def whoami(conn: GitConnection, *, client: httpx.AsyncClient | None = None) -> str:
    """The account the token belongs to: the connection test."""
    own = client is None
    client = client or _client()
    try:
        user = await _get(client, conn, "/user")
        name = user.get("login") or user.get("username") if isinstance(user, dict) else None
        if not isinstance(name, str) or not name:
            raise GitProviderError("bad_response")
        return name
    finally:
        if own:
            await client.aclose()


# ---- repositories and their webhooks (piece 1) -----------------------------------------------------------

PAGE = 50
# what a repository's webhook asks its host to send: what MegooColab follows on a task's pull request and branch
HOOK_EVENTS: dict[GitKind, list[str]] = {
    GitKind.github: ["pull_request", "pull_request_review", "pull_request_review_comment", "issue_comment", "push",
                     "check_run", "check_suite", "status"],
    GitKind.gitlab: ["push_events", "note_events", "merge_requests_events", "pipeline_events"],
    GitKind.gitea: ["push", "pull_request", "pull_request_sync", "pull_request_comment", "pull_request_review_approved",
                    "pull_request_review_rejected", "pull_request_review_comment", "issue_comment", "status"],
}


@dataclass(frozen=True)
class RepoChoice:
    path: str
    url: str
    default_branch: str | None


def _choice(item: Any, kind: GitKind) -> RepoChoice | None:
    if not isinstance(item, dict):
        return None
    path = item.get("path_with_namespace") if kind == GitKind.gitlab else item.get("full_name")
    url = item.get("web_url") if kind == GitKind.gitlab else item.get("html_url")
    branch = item.get("default_branch")
    if not isinstance(path, str) or not isinstance(url, str) or "/" not in path:
        return None
    return RepoChoice(path, url, branch if isinstance(branch, str) and branch else None)


async def list_repositories(
    conn: GitConnection, *, q: str = "", page: int = 1, client: httpx.AsyncClient | None = None
) -> tuple[list[RepoChoice], bool]:
    """The repositories the connection's token can see, PAGE at a time, matching q, and whether there are more.
    GitLab searches itself; GitHub and Gitea have no search on these lists, so their pages are filtered here
    (GitHub reads three pages of 100 for each of ours, so Load more never skips any)."""
    kind = GitKind(conn.kind)
    needle = q.strip().lower()

    async def call(c):
        if kind == GitKind.gitlab:
            params = {"membership": "true", "simple": "true", "order_by": "path", "sort": "asc", "per_page": PAGE,
                      "page": page}
            if needle:
                params["search"] = needle
            raw = await _get(c, conn, "/projects", params)
            if not isinstance(raw, list):
                raise GitProviderError("bad_response")
            return [x for x in (_choice(i, kind) for i in raw) if x], len(raw) == PAGE
        if kind == GitKind.gitea:
            raw = await _get(c, conn, "/user/repos", {"limit": PAGE, "page": page})
            if not isinstance(raw, list):
                raise GitProviderError("bad_response")
            found = [x for x in (_choice(i, kind) for i in raw) if x and needle in x.path.lower()]
            return found, len(raw) == PAGE
        found: list[RepoChoice] = []
        more = False
        for host_page in range((page - 1) * 3 + 1, page * 3 + 1):
            raw = await _get(c, conn, "/user/repos", {"per_page": 100, "page": host_page, "sort": "full_name",
                                                      "affiliation": "owner,collaborator,organization_member"})
            if not isinstance(raw, list):
                raise GitProviderError("bad_response")
            found += [x for x in (_choice(i, kind) for i in raw) if x and needle in x.path.lower()]
            more = len(raw) == 100
            if not more:
                break
        return found, more

    return await _with(client, call)


def _hooks_path(conn: GitConnection, path: str) -> str:
    if GitKind(conn.kind) == GitKind.gitlab:
        return f"/projects/{quote(path, safe='')}/hooks"
    return f"/repos/{path}/hooks"


def _hook_body(conn: GitConnection, url: str, secret: str) -> dict:
    kind = GitKind(conn.kind)
    if kind == GitKind.gitlab:
        return {"url": url, "token": secret, "enable_ssl_verification": True, **dict.fromkeys(HOOK_EVENTS[kind], True)}
    config = {"url": url, "content_type": "json", "secret": secret}
    if kind == GitKind.github:
        return {"name": "web", "active": True, "events": HOOK_EVENTS[kind], "config": {**config, "insecure_ssl": "0"}}
    return {"type": "gitea", "active": True, "events": HOOK_EVENTS[kind], "config": config}


async def _with(client: httpx.AsyncClient | None, call):
    own = client is None
    client = client or _client()
    try:
        return await call(client)
    finally:
        if own:
            await client.aclose()


async def list_hooks(conn: GitConnection, path: str, *, client: httpx.AsyncClient | None = None) -> list[tuple[str, str]]:
    """(hook id, the address it posts to) for each of the repository's webhooks."""

    async def call(c):
        page = {"limit": 50} if GitKind(conn.kind) == GitKind.gitea else {"per_page": 100}
        raw = await _get(c, conn, _hooks_path(conn, path), page)
        if not isinstance(raw, list):
            raise GitProviderError("bad_response")
        out = []
        for hook in raw:
            if not isinstance(hook, dict) or hook.get("id") is None:
                continue
            url = hook.get("url") if GitKind(conn.kind) == GitKind.gitlab else (hook.get("config") or {}).get("url")
            if isinstance(url, str):
                out.append((str(hook["id"]), url))
        return out

    return await _with(client, call)


async def create_hook(conn: GitConnection, path: str, url: str, secret: str, *, client: httpx.AsyncClient | None = None) -> str:
    async def call(c):
        made = await _send(c, conn, "POST", _hooks_path(conn, path), json=_hook_body(conn, url, secret), ok=(200, 201))
        if not isinstance(made, dict) or made.get("id") is None:
            raise GitProviderError("bad_response")
        return str(made["id"])

    return await _with(client, call)


async def update_hook(
    conn: GitConnection, path: str, hook_id: str, url: str, secret: str, *, client: httpx.AsyncClient | None = None
) -> None:
    method = "PUT" if GitKind(conn.kind) == GitKind.gitlab else "PATCH"

    async def call(c):
        await _send(c, conn, method, f"{_hooks_path(conn, path)}/{hook_id}", json=_hook_body(conn, url, secret))

    await _with(client, call)


async def delete_hook(conn: GitConnection, path: str, hook_id: str, *, client: httpx.AsyncClient | None = None) -> None:
    """Gone already counts as done."""

    async def call(c):
        try:
            await _send(c, conn, "DELETE", f"{_hooks_path(conn, path)}/{hook_id}", ok=(200, 204))
        except GitProviderError as e:
            if e.code != "not_found":
                raise

    await _with(client, call)


def hook_page_url(conn: GitConnection, path: str) -> str:
    """The host's webhook settings page for the repository."""
    web = conn.base_url.rstrip("/")
    return f"{web}/{path}/-/hooks" if GitKind(conn.kind) == GitKind.gitlab else f"{web}/{path}/settings/hooks"
