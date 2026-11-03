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


# -- piece 1: listing repositories and managing their webhooks ----------------------------------------------


def _recorder(answer):
    """A client whose handler records (method, raw path, query, JSON body) and answers answer(method, path)."""
    calls: list[tuple[str, str, dict, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode().split("?")[0]
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, path, dict(request.url.params), body))
        status, payload = answer(request.method, path)
        return httpx.Response(status, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), calls


async def test_github_lists_repositories_filtered_and_paged():
    repos = [{"full_name": "acme/pay", "html_url": "https://github.com/acme/pay", "default_branch": "main"},
             {"full_name": "acme/web", "html_url": "https://github.com/acme/web", "default_branch": "develop"}]
    client, calls = _recorder(lambda m, p: (200, repos if "page" else []))
    items, more = await providers.list_repositories(_conn("github", "https://github.com"), q="PAY", client=client)
    assert items == [providers.RepoChoice("acme/pay", "https://github.com/acme/pay", "main")] and more is False
    assert calls[0][1] == "/user/repos" and calls[0][2]["affiliation"] == "owner,collaborator,organization_member"


async def test_gitlab_lists_with_server_search():
    repos = [{"path_with_namespace": "grp/sub/pay", "web_url": "https://lab.acme.io/grp/sub/pay", "default_branch": "main"}]
    client, calls = _recorder(lambda m, p: (200, repos))
    items, more = await providers.list_repositories(_conn("gitlab", "https://lab.acme.io"), q="pay", client=client)
    assert items == [providers.RepoChoice("grp/sub/pay", "https://lab.acme.io/grp/sub/pay", "main")] and more is False
    assert calls[0][1] == "/api/v4/projects"
    assert calls[0][2]["search"] == "pay" and calls[0][2]["membership"] == "true"


async def test_gitea_lists_repositories():
    repos = [{"full_name": "o/r", "html_url": "https://tea.acme.io/o/r", "default_branch": "main"},
             {"full_name": "o/other", "html_url": "https://tea.acme.io/o/other", "default_branch": "main"}]
    client, calls = _recorder(lambda m, p: (200, repos))
    items, _ = await providers.list_repositories(_conn("gitea", "https://tea.acme.io"), q="/r", client=client)
    assert [i.path for i in items] == ["o/r"] and calls[0][1] == "/api/v1/user/repos"


async def test_github_hook_create_update_list_delete():
    conn = _conn("github", "https://github.com")

    def answer(method, path):
        if method == "POST":
            return 201, {"id": 123}
        if method == "GET":
            return 200, [{"id": 123, "config": {"url": "https://colab/x"}}]
        return 200, {}

    client, calls = _recorder(answer)
    assert await providers.create_hook(conn, "acme/pay", "https://colab/x", "s3cret", client=client) == "123"
    method, path, _, body = calls[-1]
    assert (method, path) == ("POST", "/repos/acme/pay/hooks")
    assert body["config"] == {"url": "https://colab/x", "content_type": "json", "secret": "s3cret", "insecure_ssl": "0"}
    assert body["events"] == providers.HOOK_EVENTS[providers.GitKind.github] and body["active"] is True
    await providers.update_hook(conn, "acme/pay", "123", "https://colab/x", "new", client=client)
    assert calls[-1][:2] == ("PATCH", "/repos/acme/pay/hooks/123") and calls[-1][3]["config"]["secret"] == "new"
    assert await providers.list_hooks(conn, "acme/pay", client=client) == [("123", "https://colab/x")]
    await providers.delete_hook(conn, "acme/pay", "123", client=client)
    assert calls[-1][:2] == ("DELETE", "/repos/acme/pay/hooks/123")


async def test_gitlab_hooks_use_the_encoded_path():
    conn = _conn("gitlab", "https://lab.acme.io")
    client, calls = _recorder(lambda m, p: (201, {"id": 7}) if m == "POST" else (200, [{"id": 7, "url": "https://colab/x"}]))
    assert await providers.create_hook(conn, "grp/sub/pay", "https://colab/x", "s", client=client) == "7"
    method, path, _, body = calls[-1]
    assert (method, path) == ("POST", "/api/v4/projects/grp%2Fsub%2Fpay/hooks")
    assert body["token"] == "s" and body["url"] == "https://colab/x"
    assert all(body[k] is True for k in ("push_events", "note_events", "merge_requests_events", "pipeline_events"))
    assert await providers.list_hooks(conn, "grp/sub/pay", client=client) == [("7", "https://colab/x")]
    await providers.update_hook(conn, "grp/sub/pay", "7", "https://colab/x", "s2", client=client)
    assert calls[-1][:2] == ("PUT", "/api/v4/projects/grp%2Fsub%2Fpay/hooks/7")


async def test_gitea_hook_events():
    conn = _conn("gitea", "https://tea.acme.io")
    client, calls = _recorder(lambda m, p: (201, {"id": 5}))
    await providers.create_hook(conn, "o/r", "https://colab/x", "s", client=client)
    body = calls[-1][3]
    assert body["type"] == "gitea" and body["config"]["secret"] == "s"
    assert set(body["events"]) >= {"push", "pull_request", "pull_request_review_rejected", "pull_request_comment", "status"}


async def test_a_403_without_rate_limit_is_forbidden():
    client, _ = _recorder(lambda m, p: (403, {"message": "Must have admin rights"}))
    with pytest.raises(GitProviderError) as e:
        await providers.create_hook(_conn("github", "https://github.com"), "a/b", "u", "s", client=client)
    assert e.value.code == "forbidden"


async def test_delete_hook_treats_404_as_done():
    client, _ = _recorder(lambda m, p: (404, {"message": "Not Found"}))
    await providers.delete_hook(_conn("github", "https://github.com"), "a/b", "1", client=client)


def test_hook_page_url_per_kind():
    assert providers.hook_page_url(_conn("github", "https://github.com"), "acme/pay") == "https://github.com/acme/pay/settings/hooks"
    assert providers.hook_page_url(_conn("gitlab", "https://lab.acme.io"), "grp/sub/pay") == "https://lab.acme.io/grp/sub/pay/-/hooks"
    assert providers.hook_page_url(_conn("gitea", "https://tea.acme.io"), "o/r") == "https://tea.acme.io/o/r/settings/hooks"


async def test_github_paging_reaches_every_repository():
    """Load more never skips: 350 repositories, read 100 a host page, all come back once across the picker's pages."""
    repos = [{"full_name": f"acme/r{i:03}", "html_url": f"https://github.com/acme/r{i:03}", "default_branch": "main"}
             for i in range(350)]

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        return httpx.Response(200, json=repos[(page - 1) * 100: page * 100])

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    page, more = 1, True
    while more:
        items, more = await providers.list_repositories(_conn("github", "https://github.com"), page=page, client=client)
        seen += [i.path for i in items]
        page += 1
        assert page < 20
    assert seen == [r["full_name"] for r in repos]


async def test_github_lists_hooks_100_a_page():
    client, calls = _recorder(lambda m, p: (200, []))
    await providers.list_hooks(_conn("github", "https://github.com"), "acme/pay", client=client)
    assert calls[-1][2].get("per_page") == "100"
