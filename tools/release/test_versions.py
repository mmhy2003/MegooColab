"""The release tool: version files agree, a changed product is bumped, what needs a release, the Scoop manifest."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import versions  # noqa: E402

MANIFEST = {
    "version": "0.0.0",
    "description": "Runs coding agents on this machine for MegooColab",
    "architecture": {
        "64bit": {"url": "https://example/old_amd64.zip", "hash": "0" * 64},
        "arm64": {"url": "https://example/old_arm64.zip", "hash": "0" * 64},
    },
    "bin": "megoocolab-runner.exe",
}


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def write(root: Path, path: str, text: str) -> None:
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text(text, encoding="utf-8")


def set_app_version(root: Path, version: str) -> None:
    write(root, "VERSION", f"{version}\n")
    write(root, "backend/pyproject.toml", f'[project]\nname = "megoocolab-backend"\nversion = "{version}"\n')
    write(root, "frontend/package.json", json.dumps({"name": "megoocolab-frontend", "version": version}, indent=2) + "\n")


def commit(root: Path, message: str = "change") -> None:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "T")
    set_app_version(tmp_path, "0.1.0")
    write(tmp_path, "backend/app/x.py", "x = 1\n")
    write(tmp_path, "runner/VERSION", "0.1.0\n")
    write(tmp_path, "runner/main.go", "package main\n")
    write(tmp_path, "runner/scoop/megoocolab-runner.json", json.dumps(MANIFEST, indent=4) + "\n")
    write(tmp_path, "docs/releases/v0.1.0.md", "notes\n")
    write(tmp_path, "docs/releases/runner-v0.1.0.md", "notes\n")
    commit(tmp_path, "start")
    return tmp_path


@pytest.mark.parametrize(("text", "expected"), [
    ("0.1.0", (0, 1, 0)), ("v0.10.2", (0, 10, 2)), ("dev", None), ("0.1.0-dev+abc", None), ("1.0", None), ("", None),
])
def test_parse(text, expected):
    assert versions.parse(text) == expected


def test_parts_compare_as_numbers():
    assert versions.parse("0.10.0") > versions.parse("0.9.0")


def test_check_passes_when_the_files_agree(repo):
    assert versions.check(repo) == []


def test_check_names_the_file_that_differs(repo):
    write(repo, "frontend/package.json", json.dumps({"version": "0.2.0"}))
    errors = versions.check(repo)
    assert len(errors) == 1 and "package.json" in errors[0]


def test_check_refuses_a_version_that_is_not_a_release(repo):
    write(repo, "runner/VERSION", "0.1\n")
    assert any("runner/VERSION" in e for e in versions.check(repo))


def test_guard_without_tags_has_nothing_to_guard(repo):
    write(repo, "backend/app/x.py", "x = 2\n")
    commit(repo)
    assert versions.guard(repo) == []


def test_guard_wants_a_bump_after_a_server_change(repo):
    git(repo, "tag", "v0.1.0")
    write(repo, "backend/app/x.py", "x = 2\n")
    commit(repo)
    errors = versions.guard(repo)
    assert len(errors) == 1 and "v0.1.0" in errors[0]
    set_app_version(repo, "0.1.1")
    commit(repo, "bump")
    assert versions.guard(repo) == []


def test_guard_ignores_docs(repo):
    git(repo, "tag", "v0.1.0")
    write(repo, "docs/guide.md", "words\n")
    commit(repo)
    assert versions.guard(repo) == []


def test_guard_runner_ignores_the_scoop_manifest(repo):
    git(repo, "tag", "runner-v0.1.0")
    write(repo, "runner/scoop/megoocolab-runner.json", json.dumps({**MANIFEST, "version": "0.1.0"}, indent=4) + "\n")
    commit(repo, "scoop")
    assert versions.guard(repo) == []
    write(repo, "runner/main.go", "package main // changed\n")
    commit(repo)
    errors = versions.guard(repo)
    assert len(errors) == 1 and "runner-v0.1.0" in errors[0]


def test_plan_before_any_release(repo):
    assert versions.plan(repo) == {"app": "true", "app_version": "0.1.0", "runner": "true", "runner_version": "0.1.0"}


def test_plan_skips_a_released_version(repo):
    git(repo, "tag", "v0.1.0")
    assert versions.plan(repo)["app"] == "false"


def test_plan_needs_the_release_note(repo, capsys):
    (repo / "docs/releases/runner-v0.1.0.md").unlink()
    commit(repo, "no note")
    with pytest.raises(SystemExit):
        versions.plan(repo)
    assert "docs/releases/runner-v0.1.0.md" in capsys.readouterr().err


def test_update_scoop(repo):
    manifest = repo / "runner/scoop/megoocolab-runner.json"
    checksums = (
        f"{'a' * 64}  megoocolab-runner_0.2.0_windows_amd64.zip\n"
        f"{'b' * 64}  megoocolab-runner_0.2.0_windows_arm64.zip\n"
        f"{'c' * 64}  megoocolab-runner_0.2.0_linux_amd64.tar.gz\n"
    )
    versions.update_scoop(manifest, "0.2.0", checksums)
    text = manifest.read_text(encoding="utf-8")
    data = json.loads(text)
    base = "https://github.com/mmhy2003/MegooColab/releases/download/runner-v0.2.0"
    assert data["version"] == "0.2.0"
    assert data["architecture"]["64bit"] == {"url": f"{base}/megoocolab-runner_0.2.0_windows_amd64.zip", "hash": "a" * 64}
    assert data["architecture"]["arm64"] == {"url": f"{base}/megoocolab-runner_0.2.0_windows_arm64.zip", "hash": "b" * 64}
    assert data["bin"] == "megoocolab-runner.exe"
    assert text.endswith("}\n") and '\n    "version"' in text
