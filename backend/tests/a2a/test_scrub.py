from app.a2a.scrub import scrub


def test_scrub_patterns():
    cases = {
        "key AKIAABCDEFGHIJKLMNOP here": "key [redacted] here",
        "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----": "[redacted]",
        "use sk-abcdefghijklmnopqrstuvwxyz123": "use [redacted]",
        "ghp_" + "a" * 36: "[redacted]",
        "xoxb-1234567890-abcdef": "[redacted]",
        "token mgr_" + "x" * 30: "token [redacted]",
        "password = hunter2": "password = [redacted]",
        'API_KEY: "s3cr3t value"': "API_KEY: [redacted]",
    }
    for raw, expected in cases.items():
        assert scrub(raw) == (expected, True), raw


def test_scrub_leaves_ordinary_text():
    text = "Retries use exponential backoff (see app/retry.py:10-20). The token bucket is per tenant."
    assert scrub(text) == (text, False)


def test_scrub_env_var_and_config_forms():
    """Final review: the names usually carry a prefix or suffix (DB_PASSWORD, client_secret, stripeApiKey)."""
    cases = {
        "DB_PASSWORD=hunter2": "DB_PASSWORD=[redacted]",
        "GITHUB_TOKEN: abc123": "GITHUB_TOKEN: [redacted]",
        'client_secret = "zzz"': "client_secret = [redacted]",
        "stripeApiKey=foo": "stripeApiKey=[redacted]",
        "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI": "AWS_SECRET_ACCESS_KEY=[redacted]",
        '{"password": "pa ss"}': '{"password": [redacted]}',
        "Authorization: Bearer abcdefghijklmnop": "Authorization: Bearer [redacted]",
    }
    for raw, expected in cases.items():
        assert scrub(raw) == (expected, True), raw
