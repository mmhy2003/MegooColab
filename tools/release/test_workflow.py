"""What release.yml must do that only a real release would otherwise show."""

import re
from pathlib import Path

WORKFLOW = (Path(__file__).parents[2] / ".github/workflows/release.yml").read_text(encoding="utf-8")
ROUTINE = (Path(__file__).parents[2] / "docs/releasing.md").read_text(encoding="utf-8")


def test_the_start_up_check_pulls_the_other_services():
    """--pull never would apply to the database, search, Valkey and Caddy too: not cached on a fresh runner."""
    up = next(line for line in WORKFLOW.splitlines() if "compose -p smoke" in line and " up " in line)
    assert "--pull never" not in up and "--pull missing" in up


def test_a_rerun_skips_a_release_already_created():
    """The runner job can fail after its release exists (the Scoop push): a re-run must get past it."""
    creates = re.findall(r'gh release create "(v|runner-v)\$VERSION"', WORKFLOW)
    assert creates == ["v", "runner-v"]
    for tag in ("v", "runner-v"):
        assert f'gh release view "{tag}$VERSION"' in WORKFLOW


def test_the_routine_adds_the_release_notes():
    """`git commit -am` leaves new (untracked) release notes out of the release commit."""
    assert "commit -am" not in ROUTINE
    assert "git add VERSION backend/pyproject.toml frontend/package.json runner/VERSION docs/releases" in ROUTINE
