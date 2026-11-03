"""Reading a webhook delivery into the events a task's Activity shows (piece 2): pushes, pull requests, comments,
reviews, per provider, and nothing from what they don't recognise."""

from app.git.events import GitEvent, excerpt, parse_delivery
from app.git.models import GitKind

GH = GitKind.github


def _gh(event: str, payload) -> list[GitEvent]:
    return parse_delivery(GH, {"x-github-event": event}, payload)


REPO = {"full_name": "acme/pay"}
PR = {"number": 42, "html_url": "https://github.com/acme/pay/pull/42", "title": "Retries",
      "head": {"ref": "megoo/PAY-7-retries"}, "base": {"ref": "main"}, "merged": False}


def test_github_push():
    (e,) = _gh("push", {
        "ref": "refs/heads/megoo/PAY-7-retries", "after": "abc123", "compare": "https://github.com/acme/pay/compare/x",
        "repository": REPO, "pusher": {"name": "mo"}, "sender": {"login": "mo"},
        "commits": [{"message": "fix: back off\n\nlonger body"}, {"message": "test: retries"}],
    })
    assert (e.kind, e.path, e.number, e.branch) == ("git.pushed", "acme/pay", None, "megoo/PAY-7-retries")
    assert e.actor == {"name": "mo", "login": "mo"}
    assert e.data == {"commits": 2, "titles": ["fix: back off", "test: retries"], "head_sha": "abc123",
                      "compare_url": "https://github.com/acme/pay/compare/x"}


def test_github_push_deleting_a_branch_is_nothing():
    assert _gh("push", {"ref": "refs/heads/megoo/PAY-7", "deleted": True, "repository": REPO, "commits": []}) == []


def test_github_pr_opened_merged_closed():
    who = {"sender": {"login": "mo"}, "repository": REPO}
    (opened,) = _gh("pull_request", {"action": "opened", "pull_request": PR, **who})
    assert (opened.kind, opened.number, opened.branch) == ("git.pr_opened", 42, "megoo/PAY-7-retries")
    assert opened.data == {"url": PR["html_url"], "title": "Retries", "base": "main"}
    (merged,) = _gh("pull_request", {"action": "closed", "pull_request": {**PR, "merged": True}, **who})
    (closed,) = _gh("pull_request", {"action": "closed", "pull_request": PR, **who})
    assert (merged.kind, closed.kind) == ("git.pr_merged", "git.pr_closed")
    assert merged.data == {"url": PR["html_url"]} and merged.actor == {"name": "mo", "login": "mo"}
    assert _gh("pull_request", {"action": "edited", "pull_request": PR, **who}) == []


def test_github_comment_review_and_line_comment():
    who = {"sender": {"login": "rev"}, "repository": REPO}
    (c,) = _gh("issue_comment", {"action": "created", **who, "issue": {"number": 42, "pull_request": {"url": "x"}},
                                 "comment": {"body": "Looks good", "html_url": "https://github.com/c/1"}})
    assert (c.kind, c.number, c.branch) == ("git.commented", 42, None)
    assert c.data == {"url": "https://github.com/c/1", "excerpt": "Looks good"}
    assert _gh("issue_comment", {"action": "created", **who, "issue": {"number": 3}, "comment": {"body": "x"}}) == []
    verdicts = {}
    for state in ("approved", "changes_requested", "commented", "APPROVED"):
        (r,) = _gh("pull_request_review", {"action": "submitted", **who, "pull_request": PR,
                                           "review": {"id": 9, "state": state, "body": "Two things",
                                                      "html_url": "https://github.com/r/9"}})
        verdicts[state] = r.data["verdict"]
    assert verdicts == {"approved": "approved", "changes_requested": "changes_requested", "commented": "commented",
                        "APPROVED": "approved"}
    assert r.kind == "git.reviewed" and r.data == {"review_id": "9", "verdict": "approved", "excerpt": "Two things",
                                                   "url": "https://github.com/r/9"}
    assert _gh("pull_request_review", {"action": "submitted", **who, "pull_request": PR,
                                       "review": {"id": 9, "state": "commented", "body": ""}}) == []
    (lc,) = _gh("pull_request_review_comment", {"action": "created", **who, "pull_request": PR,
                                                "comment": {"pull_request_review_id": 9, "path": "src/a.py", "line": 88,
                                                            "body": "Add a delay", "html_url": "https://github.com/c/2"}})
    assert (lc.kind, lc.branch) == ("git.review_comment", "megoo/PAY-7-retries")
    assert lc.data == {"review_id": "9", "file": "src/a.py", "line": 88, "excerpt": "Add a delay",
                       "url": "https://github.com/c/2"}


def test_gitlab_push_mr_and_note():
    gl = lambda event, payload: parse_delivery(GitKind.gitlab, {"x-gitlab-event": event}, payload)
    project = {"path_with_namespace": "grp/sub/pay"}
    (p,) = gl("Push Hook", {"ref": "refs/heads/megoo/PAY-7-x", "after": "f" * 40, "project": project,
                            "user_name": "Mo Y", "user_username": "mo", "total_commits_count": 5,
                            "commits": [{"message": "one"}]})
    assert (p.kind, p.path, p.branch, p.actor) == ("git.pushed", "grp/sub/pay", "megoo/PAY-7-x", {"name": "Mo Y", "login": "mo"})
    assert p.data["commits"] == 5 and p.data["titles"] == ["one"]
    assert gl("Push Hook", {"ref": "refs/heads/x", "after": "0" * 40, "project": project, "commits": []}) == []
    attrs = {"iid": 3, "url": "https://lab/grp/sub/pay/-/merge_requests/3", "title": "T", "source_branch": "megoo/PAY-7-x",
             "target_branch": "main"}
    user = {"name": "Mo Y", "username": "mo"}
    kinds = [gl("Merge Request Hook", {"object_attributes": {**attrs, "action": a}, "project": project, "user": user})[0]
             for a in ("open", "merge", "close", "approved")]
    assert [k.kind for k in kinds] == ["git.pr_opened", "git.pr_merged", "git.pr_closed", "git.reviewed"]
    assert kinds[0].data == {"url": attrs["url"], "title": "T", "base": "main"} and kinds[0].branch == "megoo/PAY-7-x"
    assert kinds[3].data["verdict"] == "approved"
    (n,) = gl("Note Hook", {"object_attributes": {"noteable_type": "MergeRequest", "note": "why?", "url": "https://lab/n/1",
                                                  "position": {"new_path": "src/a.py", "new_line": 12}},
                            "merge_request": {"iid": 3, "source_branch": "megoo/PAY-7-x"}, "project": project, "user": user})
    assert (n.kind, n.number, n.branch) == ("git.commented", 3, "megoo/PAY-7-x")
    assert n.data == {"url": "https://lab/n/1", "excerpt": "why?", "file": "src/a.py", "line": 12}
    assert gl("Note Hook", {"object_attributes": {"noteable_type": "Issue", "note": "x"}, "project": project}) == []


def test_gitea_push_pr_and_reviews():
    tea = lambda event, payload: parse_delivery(
        GitKind.gitea, {"x-gitea-event": event, "x-github-event": "ignored"}, payload)
    sender = {"login": "mo", "full_name": "Mo Y"}
    (p,) = tea("push", {"ref": "refs/heads/megoo/PAY-7-x", "after": "a1", "compare_url": "https://tea/c", "repository": REPO,
                        "pusher": sender, "commits": [{"message": "one"}]})
    assert (p.kind, p.actor, p.data["compare_url"]) == ("git.pushed", {"name": "Mo Y", "login": "mo"}, "https://tea/c")
    (o,) = tea("pull_request", {"action": "opened", "pull_request": PR, "repository": REPO, "sender": sender})
    assert o.kind == "git.pr_opened" and o.actor == {"name": "Mo Y", "login": "mo"}
    review = {"pull_request": PR, "repository": REPO, "sender": sender, "review": {"content": "Fix it"}}
    got = {ev: tea(ev, review)[0].data["verdict"] for ev in
           ("pull_request_review_approved", "pull_request_review_rejected", "pull_request_review_comment")}
    assert got == {"pull_request_review_approved": "approved", "pull_request_review_rejected": "changes_requested",
                   "pull_request_review_comment": "commented"}
    (c,) = tea("issue_comment", {"action": "created", "is_pull": True, "issue": {"number": 42}, "repository": REPO,
                                 "sender": sender, "comment": {"body": "ok", "html_url": "https://tea/c/1"}})
    assert c.kind == "git.commented" and c.number == 42


def test_excerpt_collapses_and_cuts():
    out = excerpt("a\n\n  b" + "x" * 400)
    assert out.startswith("a b") and len(out) <= 280 and out.endswith("…")
    assert excerpt(None) == "" and excerpt("  short ") == "short"


def test_odd_payloads_parse_to_nothing():
    for event, payload in [
        ("push", None), ("push", []), ("push", {"commits": None}),
        ("pull_request", {"pull_request": None, "action": "opened"}),
        ("push", {"ref": "refs/heads/x", "repository": REPO, "commits": "x"}),
        ("pull_request_review", {"action": "submitted", "review": None, "pull_request": PR, "repository": REPO}),
        ("ping", {"zen": "x"}),
    ]:
        assert _gh(event, payload) == [], (event, payload)
    (odd,) = _gh("push", {"ref": "refs/heads/x", "after": "a", "repository": REPO, "pusher": {"name": "mo"},
                          "commits": [{"message": 5}, "y"]})
    assert odd.data["titles"] == [] and odd.data["commits"] == 2
    assert parse_delivery(GitKind.gitlab, {}, {"object_kind": "push"}) == []
