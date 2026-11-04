"""Final-review fixes for the Secrets Store."""

import json
import re
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.secrets.blanking import blank
from app.secrets.names import RESERVED, RESERVED_PREFIXES, check_name
from tests.factories import login, make_project, make_user

RUNNER_SECRETS = Path(__file__).resolve().parents[3] / "runner" / "internal" / "jobs" / "secrets.go"


@pytest.mark.parametrize("name", [
    "NODE_OPTIONS", "NODE_TLS_REJECT_UNAUTHORIZED", "NODE_EXTRA_CA_CERTS", "NPM_CONFIG_REGISTRY", "LD_PRELOAD",
    "DYLD_INSERT_LIBRARIES", "BASH_ENV", "ENV", "PROMPT_COMMAND", "PS4", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY",
    "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "JAVA_TOOL_OPTIONS",
    "PYTHONPATH", "PYTHONSTARTUP", "PERL5LIB", "RUBYOPT", "HOMEDRIVE", "HOMEPATH", "PSMODULEPATH",
])
def test_names_that_run_code_or_intercept_traffic_are_reserved(name):
    with pytest.raises(HTTPException) as e:
        check_name(name)
    assert e.value.detail == "secret_name_reserved"


def test_the_runner_refuses_exactly_the_same_names():
    go = RUNNER_SECRETS.read_text(encoding="utf-8")
    names = set(re.findall(r'"([A-Z0-9_]+)": true', go))
    prefixes = re.search(r"var reservedPrefixes = \[\]string\{([^}]*)\}", go).group(1)
    assert names == set(RESERVED)
    assert set(re.findall(r'"([A-Z0-9_]+)"', prefixes)) == set(RESERVED_PREFIXES)


def test_a_name_with_a_trailing_newline_is_invalid():
    with pytest.raises(HTTPException) as e:
        check_name("API_KEY\n")
    assert e.value.detail == "secret_name_invalid"


async def test_a_refused_body_never_echoes_the_value(client, db):
    await login(client, await make_user(db))
    r = await client.post("/api/secrets", json={"description": "x", "value": "hunter2-super-secret"})
    assert r.status_code == 422 and "hunter2-super-secret" not in r.text
    sid = (await client.post("/api/secrets", json={"name": "A_KEY", "description": "x", "value": "abcd"})).json()["id"]
    r = await client.put(f"/api/secrets/{sid}/value", json={"value": "y" * 32_769})
    assert r.status_code == 422 and "yyyyyyyy" not in r.text


def test_encoded_forms_of_a_value_are_blanked():
    secrets = {"DB": "p@ss:w/rd x+y"}
    assert blank("postgres://u:p%40ss%3Aw%2Frd%20x%2By@h/db", secrets) == "postgres://u:[DB]@h/db"
    assert blank("q=p%40ss%3Aw%2Frd+x%2By", secrets) == "q=[DB]"
    quoted = {"PW": 'pa"ss\\word'}
    assert blank(json.dumps({"v": 'pa"ss\\word'}), quoted) == '{"v": "[PW]"}'
    assert blank("token: tok-12345", {"T": "tok-12345\n"}) == "token: [T]"


async def test_a_closed_projects_secrets_can_still_be_deleted(client, db):
    await make_project(client, db, "PAY")
    sid = (await client.post("/api/projects/PAY/secrets",
                             json={"name": "OLD_KEY", "description": "x", "value": "abcd1234"})).json()["id"]
    assert (await client.put("/api/projects/PAY/status", json={"status": "finished"})).status_code == 200
    assert (await client.delete(f"/api/projects/PAY/secrets/{sid}")).status_code == 204
