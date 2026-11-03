"""What a verified webhook delivery says happened, for the task's Activity (piece 2): pushes, pull requests opened,
merged or closed, comments, reviews and their line comments. Only the few fields an Activity entry shows are read;
anything unrecognised or oddly shaped reads as nothing."""

import re
from collections.abc import Mapping
from dataclasses import dataclass

from app.git.models import GitKind

EXCERPT = 280
TITLES = 3
_ZEROS = re.compile(r"^0+$")
_GITEA_REVIEWS = {"pull_request_approved": "approved", "pull_request_rejected": "changes_requested",
                  "pull_request_comment": "commented"}


@dataclass(frozen=True)
class GitEvent:
    kind: str  # git.pushed | git.pr_opened | git.commented | git.reviewed | git.review_comment | git.pr_merged | git.pr_closed
    path: str  # the repository's path on its host, e.g. "acme/pay" or "grp/sub/pay"
    number: int | None  # the pull request (None for a push)
    branch: str | None  # a push's branch; a pull request's head branch when the payload has it
    actor: dict  # {"name": str, "login": str | None}
    data: dict


def excerpt(text: object, limit: int = EXCERPT) -> str:
    """Plain text on one line, cut to `limit` characters with an ellipsis."""
    if not isinstance(text, str):
        return ""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _dict(v: object) -> dict:
    return v if isinstance(v, dict) else {}


def _str(v: object) -> str | None:
    return v if isinstance(v, str) and v else None


def _int(v: object) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None


def _branch(ref: object) -> str | None:
    ref = _str(ref)
    return ref.removeprefix("refs/heads/") if ref and ref.startswith("refs/heads/") else None


def _who(name: object, login: object) -> dict | None:
    name, login = _str(name), _str(login)
    return {"name": name or login, "login": login} if name or login else None


def _titles(commits: list) -> list[str]:
    titles = [excerpt(c.get("message", "").split("\n", 1)[0]) for c in commits if isinstance(c, dict) and _str(c.get("message"))]
    return [t for t in titles if t][:TITLES]


def parse_delivery(kind: GitKind, headers: Mapping[str, str], payload: object) -> list[GitEvent]:
    """The events in one delivery, read by the provider's own event name."""
    if not isinstance(payload, dict):
        return []
    if kind == GitKind.gitlab:
        return _gitlab(headers.get("x-gitlab-event", ""), payload)
    event = headers.get("x-gitea-event") if kind == GitKind.gitea else None
    return _github_like(kind, event or headers.get("x-github-event", ""), payload)


# ---- GitHub and Gitea ----------------------------------------------------------------------------


def _sender(kind: GitKind, user: object) -> dict | None:
    user = _dict(user)
    return _who(user.get("full_name") if kind == GitKind.gitea else None, user.get("login"))


def _github_like(kind: GitKind, event: str, p: dict) -> list[GitEvent]:
    path = _str(_dict(p.get("repository")).get("full_name"))
    if path is None:
        return []
    action = p.get("action")
    if event == "push":
        return _push_github_like(kind, path, p)
    pr = _dict(p.get("pull_request"))
    number, branch = _int(pr.get("number")), _str(_dict(pr.get("head")).get("ref"))
    actor = _sender(kind, p.get("sender"))
    if event == "pull_request" and number and actor:
        url = _str(pr.get("html_url"))
        if action == "opened":
            data = {"url": url, "title": excerpt(pr.get("title")), "base": _str(_dict(pr.get("base")).get("ref"))}
            return [GitEvent("git.pr_opened", path, number, branch, actor, data)]
        if action == "closed":
            return [GitEvent("git.pr_merged" if pr.get("merged") is True else "git.pr_closed", path, number, branch,
                             actor, {"url": url})]
        return []
    if event == "issue_comment" and action == "created" and actor:
        issue, comment = _dict(p.get("issue")), _dict(p.get("comment"))
        on_pr = issue.get("pull_request") is not None or p.get("is_pull") is True
        number = _int(issue.get("number"))
        if not on_pr or number is None:
            return []
        data = {"url": _str(comment.get("html_url")), "excerpt": excerpt(comment.get("body"))}
        return [GitEvent("git.commented", path, number, None, actor, data)]
    if event == "pull_request_review" and action == "submitted" and number and actor:
        review = _dict(p.get("review"))
        if not review:
            return []
        state = str(review.get("state") or "").lower()
        verdict = state if state in ("approved", "changes_requested") else "commented"
        body = excerpt(review.get("body"))
        if verdict == "commented" and not body:
            return []  # only its line comments carry anything, and they are folded into it
        review_id = review.get("id")
        data = {"review_id": None if review_id is None else str(review_id), "verdict": verdict, "excerpt": body,
                "url": _str(review.get("html_url"))}
        return [GitEvent("git.reviewed", path, number, branch, actor, data)]
    if event == "pull_request_review_comment" and action == "created" and number and actor:
        comment = _dict(p.get("comment"))
        review_id = comment.get("pull_request_review_id")
        if review_id is None:
            return []
        data = {"review_id": str(review_id), "file": _str(comment.get("path")),
                "line": _int(comment.get("line")) or _int(comment.get("original_line")),
                "excerpt": excerpt(comment.get("body")), "url": _str(comment.get("html_url"))}
        return [GitEvent("git.review_comment", path, number, branch, actor, data)]
    # Gitea's X-Gitea-Event names a review pull_request_approved / _rejected / _comment; X-Gitea-Event-Type (and
    # older docs) say pull_request_review_*: both are read
    verdict = _GITEA_REVIEWS.get(event.replace("pull_request_review_", "pull_request_"))
    if kind == GitKind.gitea and verdict and number and actor:
        data = {"review_id": None, "verdict": verdict, "excerpt": excerpt(_dict(p.get("review")).get("content")),
                "url": _str(pr.get("html_url"))}
        return [GitEvent("git.reviewed", path, number, branch, actor, data)]
    return []


def _push_github_like(kind: GitKind, path: str, p: dict) -> list[GitEvent]:
    branch, commits = _branch(p.get("ref")), p.get("commits")
    if branch is None or p.get("deleted") is True or not isinstance(commits, list) or not commits:
        return []
    pusher = _dict(p.get("pusher"))
    if kind == GitKind.gitea:
        actor = _who(pusher.get("full_name"), pusher.get("login") or pusher.get("username"))
    else:
        actor = _who(None, pusher.get("name")) or _sender(kind, p.get("sender"))
    after = _str(p.get("after"))
    if actor is None or after is None or _ZEROS.match(after):
        return []
    data = {"commits": len(commits), "titles": _titles(commits), "head_sha": after,
            "compare_url": _str(p.get("compare_url") if kind == GitKind.gitea else p.get("compare"))}
    return [GitEvent("git.pushed", path, None, branch, actor, data)]


# ---- GitLab ----------------------------------------------------------------------------------


def _gitlab(event: str, p: dict) -> list[GitEvent]:
    path = _str(_dict(p.get("project")).get("path_with_namespace"))
    if path is None:
        return []
    if event == "Push Hook":
        branch, commits, after = _branch(p.get("ref")), p.get("commits"), _str(p.get("after"))
        actor = _who(p.get("user_name"), p.get("user_username"))
        if branch is None or after is None or _ZEROS.match(after) or not isinstance(commits, list) or actor is None:
            return []
        count = _int(p.get("total_commits_count")) or len(commits)
        if not count:
            return []
        data = {"commits": count, "titles": _titles(commits), "head_sha": after, "compare_url": None}
        return [GitEvent("git.pushed", path, None, branch, actor, data)]
    user = _dict(p.get("user"))
    actor = _who(user.get("name"), user.get("username"))
    if actor is None:
        return []
    attrs = _dict(p.get("object_attributes"))
    if event == "Merge Request Hook":
        number, branch, url = _int(attrs.get("iid")), _str(attrs.get("source_branch")), _str(attrs.get("url"))
        if number is None:
            return []
        action = attrs.get("action")
        if action == "open":
            data = {"url": url, "title": excerpt(attrs.get("title")), "base": _str(attrs.get("target_branch"))}
            return [GitEvent("git.pr_opened", path, number, branch, actor, data)]
        if action in ("merge", "close"):
            return [GitEvent("git.pr_merged" if action == "merge" else "git.pr_closed", path, number, branch, actor,
                             {"url": url})]
        if action == "approved":
            data = {"review_id": None, "verdict": "approved", "excerpt": "", "url": url}
            return [GitEvent("git.reviewed", path, number, branch, actor, data)]
        return []
    # a note edited (newer GitLab sends those too) or written by GitLab itself is not a new comment
    is_new = attrs.get("action") in (None, "create") and attrs.get("system") is not True
    if event == "Note Hook" and attrs.get("noteable_type") == "MergeRequest" and is_new:
        mr = _dict(p.get("merge_request"))
        number = _int(mr.get("iid"))
        if number is None:
            return []
        data = {"url": _str(attrs.get("url")), "excerpt": excerpt(attrs.get("note"))}
        position = _dict(attrs.get("position"))
        if _str(position.get("new_path")):
            data |= {"file": position["new_path"], "line": _int(position.get("new_line"))}
        return [GitEvent("git.commented", path, number, _str(mr.get("source_branch")), actor, data)]
    return []
