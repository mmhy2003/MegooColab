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
