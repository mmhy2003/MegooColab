"""Provider clients (GIT-1, GIT-3): pull-request URL parsing and status mapping, against mocked HTTP only."""

import json

import httpx
import pytest

from app.core.crypto import encrypt
from app.git import providers
from app.git.models import GitConnection
from app.git.providers import GitProviderError, PrRef


def _conn(kind: str, base_url: str) -> GitConnection:
    return GitConnection(name=kind, kind=kind, base_url=base_url, token_enc=encrypt("tok-123"))


def _client(routes: dict[str, object], seen: list[httpx.Request] | None = None) -> httpx.AsyncClient:
    """routes: request path -> JSON body, an int status, or an Exception to raise."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        out = routes.get(request.url.raw_path.decode().split("?")[0])  # raw: GitLab project paths stay %2F-encoded
        if isinstance(out, Exception):
            raise out
        if isinstance(out, int):
            return httpx.Response(out, json={"message": "x"})
        if out is None:
            return httpx.Response(404, json={"message": "Not Found"})
        if isinstance(out, str):
            return httpx.Response(200, text=out)
        return httpx.Response(200, json=out)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_parse_pr_url_shapes():
    gh = _conn("github", "https://github.com")
    assert providers.parse_pr_url("https://github.com/acme/pay/pull/12", gh) == PrRef("github", "https://github.com", "acme/pay", 12)
    assert providers.parse_pr_url("https://GitHub.com/acme/pay/pull/12/files?x=1#y", gh) is None  # only the PR itself
    ghe = _conn("github", "https://git.acme.io/ghe")
    assert providers.parse_pr_url("https://git.acme.io/ghe/acme/pay/pull/3", ghe).path == "acme/pay"
    gl = _conn("gitlab", "https://gitlab.acme.io")
    ref = providers.parse_pr_url("https://gitlab.acme.io/grp/sub/pay/-/merge_requests/7", gl)
    assert (ref.path, ref.number) == ("grp/sub/pay", 7)
    gt = _conn("gitea", "http://gitea.local:3000")
    assert providers.parse_pr_url("http://gitea.local:3000/o/r/pulls/5", gt).number == 5
    for bad in ("https://evil.example/acme/pay/pull/12", "https://github.com/acme/pay/pull/", "https://github.com/acme/pull/1",
                "javascript:alert(1)", "https://github.com/acme/pay/pulls/12", "", "https://github.com.evil.io/acme/pay/pull/1",
                "http://github.com/acme/pay/pull/12"):
        assert providers.parse_pr_url(bad, gh) is None, bad
    assert providers.parse_pr_url("https://gitlab.acme.io/pay/-/merge_requests/7", gl) is None  # a group is required


def test_repo_path_forms():
    assert providers.repo_path("https://h.io/o/r.git") == "o/r"
    assert providers.repo_path("https://h.io/o/r/") == "o/r"
    assert providers.repo_path("git@h.io:o/r.git") == "o/r"
    assert providers.repo_path("ssh://git@h.io:22/g/sub/r") == "g/sub/r"
    assert providers.repo_path("/local/path") is None and providers.repo_path("not a url") is None


async def test_github_status_mapping():
    conn = _conn("github", "https://github.com")
    ref = PrRef("github", "https://github.com", "acme/pay", 12)
    base = "/repos/acme/pay"
    pr = {"state": "open", "merged": False, "merged_at": None, "head": {"sha": "abc"}}
    seen: list[httpx.Request] = []
    routes = {
        f"{base}/pulls/12": pr,
        f"{base}/commits/abc/status": {"state": "pending", "total_count": 0, "statuses": []},
        f"{base}/commits/abc/check-runs": {"check_runs": [{"status": "completed", "conclusion": "success"},
                                                          {"status": "in_progress", "conclusion": None}]},
        f"{base}/pulls/12/reviews": [
            {"user": {"login": "ann"}, "state": "CHANGES_REQUESTED"},
            {"user": {"login": "bob"}, "state": "COMMENTED"},
            {"user": {"login": "ann"}, "state": "APPROVED"},
        ],
    }
    st = await providers.fetch_pr(conn, ref, client=_client(routes, seen))
    assert (st.state, st.checks, st.review, st.head_sha) == ("open", "pending", "approved", "abc")
    assert all(r.url.host == "api.github.com" for r in seen)
    assert seen[0].headers["Authorization"] == "Bearer tok-123" and seen[0].headers["X-GitHub-Api-Version"] == "2022-11-28"
    routes[f"{base}/commits/abc/check-runs"] = {"check_runs": [{"status": "completed", "conclusion": "timed_out"}]}
    assert (await providers.fetch_pr(conn, ref, client=_client(routes))).checks == "failure"
    routes[f"{base}/commits/abc/check-runs"] = {"check_runs": []}
    assert (await providers.fetch_pr(conn, ref, client=_client(routes))).checks == "none"
    routes[f"{base}/commits/abc/status"] = {"state": "success", "total_count": 1, "statuses": [{"state": "success"}]}
    assert (await providers.fetch_pr(conn, ref, client=_client(routes))).checks == "success"
    routes[f"{base}/pulls/12"] = {**pr, "state": "closed", "merged": True, "merged_at": "2026-10-27T10:00:00Z"}
    st = await providers.fetch_pr(conn, ref, client=_client(routes))
    assert st.state == "merged" and st.merged_at is not None
    routes[f"{base}/pulls/12"] = {**pr, "state": "closed"}
    assert (await providers.fetch_pr(conn, ref, client=_client(routes))).state == "closed"


async def test_github_enterprise_api_base():
    conn = _conn("github", "https://git.acme.io")
    seen: list[httpx.Request] = []
    routes = {"/api/v3/user": {"login": "megoo-bot"}}
    assert await providers.whoami(conn, client=_client(routes, seen)) == "megoo-bot"
    assert str(seen[0].url) == "https://git.acme.io/api/v3/user"


async def test_gitlab_status_mapping():
    conn = _conn("gitlab", "https://gitlab.acme.io")
    ref = PrRef("gitlab", "https://gitlab.acme.io", "grp/sub/pay", 7)
    mr_path = "/api/v4/projects/grp%2Fsub%2Fpay/merge_requests/7"
    seen: list[httpx.Request] = []
    routes = {
        mr_path: {"state": "opened", "merged_at": None, "sha": "def", "head_pipeline": {"status": "running"}},
        f"{mr_path}/approvals": {"approved": True},
    }
    st = await providers.fetch_pr(conn, ref, client=_client(routes, seen))
    assert (st.state, st.checks, st.review, st.head_sha) == ("open", "pending", "approved", "def")
    assert seen[0].headers["PRIVATE-TOKEN"] == "tok-123" and "Authorization" not in seen[0].headers
    assert seen[0].url.raw_path.decode().startswith("/api/v4/projects/grp%2Fsub%2Fpay/")
    routes[mr_path] = {"state": "merged", "merged_at": "2026-10-27T10:00:00Z", "sha": "def", "head_pipeline": {"status": "failed"}}
    st = await providers.fetch_pr(conn, ref, client=_client(routes))
    assert (st.state, st.checks) == ("merged", "failure")
    routes[mr_path] = {"state": "locked", "sha": "def", "head_pipeline": None}
    routes[f"{mr_path}/approvals"] = 404  # approvals unavailable: no review, not an error
    st = await providers.fetch_pr(conn, ref, client=_client(routes))
    assert (st.state, st.checks, st.review) == ("closed", "none", "none")


async def test_gitea_status_mapping():
    conn = _conn("gitea", "http://gitea.local:3000")
    ref = PrRef("gitea", "http://gitea.local:3000", "o/r", 5)
    base = "/api/v1/repos/o/r"
    seen: list[httpx.Request] = []
    routes = {
        f"{base}/pulls/5": {"state": "open", "merged": False, "merged_at": None, "head": {"sha": "f00"}},
        f"{base}/commits/f00/status": {"state": "error", "total_count": 1},
        f"{base}/pulls/5/reviews": [{"user": {"login": "ann"}, "state": "REQUEST_CHANGES"}],
    }
    st = await providers.fetch_pr(conn, ref, client=_client(routes, seen))
    assert (st.state, st.checks, st.review) == ("open", "failure", "changes_requested")
    assert seen[0].headers["Authorization"] == "token tok-123"
    routes[f"{base}/pulls/5"] = {"state": "closed", "merged": True, "merged_at": "2026-10-27T10:00:00Z", "head": {"sha": "f00"}}
    routes[f"{base}/commits/f00/status"] = {"state": "success", "total_count": 2}
    routes[f"{base}/pulls/5/reviews"] = [{"user": {"login": "ann"}, "state": "APPROVED"}]
    st = await providers.fetch_pr(conn, ref, client=_client(routes))
    assert (st.state, st.checks, st.review) == ("merged", "success", "approved")


@pytest.mark.parametrize(("reply", "code"), [
    (401, "unauthorized"),
    (404, "not_found"),
    (429, "rate_limited"),
    (500, "bad_response"),
    (httpx.ConnectTimeout("slow"), "unreachable"),
    (httpx.ConnectError("refused"), "unreachable"),
    ("<html>not json</html>", "bad_response"),
    ({"unexpected": True}, "bad_response"),
])
async def test_provider_errors_map_to_codes(reply, code):
    conn = _conn("github", "https://github.com")
    with pytest.raises(GitProviderError) as e:
        await providers.fetch_pr(conn, PrRef("github", "https://github.com", "a/b", 1),
                                 client=_client({"/repos/a/b/pulls/1": reply}))
    assert e.value.code == code
    assert "tok-123" not in str(e.value)


async def test_github_secondary_rate_limit_is_rate_limited():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, headers={"X-RateLimit-Remaining": "0"}, content=json.dumps({"message": "x"}))

    with pytest.raises(GitProviderError) as e:
        await providers.whoami(_conn("github", "https://github.com"),
                               client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert e.value.code == "rate_limited"


async def test_redirect_to_another_host_is_not_followed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://evil.example/steal"})

    with pytest.raises(GitProviderError) as e:
        await providers.whoami(_conn("gitea", "https://gitea.acme.io"),
                               client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert e.value.code == "bad_response"
