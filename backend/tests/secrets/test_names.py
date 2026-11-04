import pytest
from fastapi import HTTPException

from app.secrets.names import check_name


def test_a_good_name_passes():
    check_name("STAGING_DB_PASSWORD")
    check_name("A")
    check_name("A" * 100)


@pytest.mark.parametrize("name", ["staging", "1ABC", "A-B", "A" * 101, "", "_X", "A B"])
def test_bad_names_are_invalid(name):
    with pytest.raises(HTTPException) as e:
        check_name(name)
    assert e.value.status_code == 422 and e.value.detail == "secret_name_invalid"


@pytest.mark.parametrize("name", ["PATH", "HOME", "USERPROFILE", "MEGOO_X", "MEGOOCOLAB", "ANTHROPIC_API_KEY",
                                  "CLAUDE_CODE_X", "OPENAI_API_KEY", "CODEX_HOME", "OMP_X", "GIT_SSH_COMMAND",
                                  "LC_ALL", "SSH_AUTH_SOCK", "TMPDIR"])
def test_names_the_runner_relies_on_are_reserved(name):
    with pytest.raises(HTTPException) as e:
        check_name(name)
    assert e.value.status_code == 422 and e.value.detail == "secret_name_reserved"
