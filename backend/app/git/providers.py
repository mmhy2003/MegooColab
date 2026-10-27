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
    """A provider call failed: unauthorized | not_found | unreachable | rate_limited | bad_response."""

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


async def _get(client: httpx.AsyncClient, conn: GitConnection, path: str) -> Any:
    try:
        r = await client.get(api_base(conn) + path, headers=_headers(conn))
    except httpx.HTTPError:
        raise GitProviderError("unreachable") from None
    if r.status_code == 401:
        raise GitProviderError("unauthorized")
    if r.status_code == 404:
        raise GitProviderError("not_found")
    if r.status_code == 429 or (r.status_code == 403 and r.headers.get("X-RateLimit-Remaining") == "0"):
        raise GitProviderError("rate_limited")
    if r.status_code != 200:
        raise GitProviderError("bad_response")
    try:
        return r.json()
    except ValueError:
        raise GitProviderError("bad_response") from None


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
