from app.core.crypto import decrypt, encrypt


def test_encrypt_roundtrip():
    token = encrypt("smtp-pass")
    assert token != "smtp-pass"
    assert decrypt(token) == "smtp-pass"
