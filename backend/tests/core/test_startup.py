import pytest

from app.main import validate_secret_key


@pytest.mark.parametrize("key", ["", "short", "CHANGE_ME_generate_with_openssl_rand_hex_32"])
def test_weak_or_example_secret_key_refused(key):
    with pytest.raises(RuntimeError):
        validate_secret_key(key)


def test_strong_secret_key_accepted():
    validate_secret_key("9f2c4b1e8d7a6c5b4a3f2e1d0c9b8a7f")
