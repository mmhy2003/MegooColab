import hashlib
import secrets

from pwdlib import PasswordHash

_password_hash = PasswordHash.recommended()
# Verified against when the account is unknown, so response time doesn't reveal it.
DUMMY_HASH = _password_hash.hash("dummy-password-for-timing")


def hash_password(pw: str) -> str:
    return _password_hash.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    return _password_hash.verify(pw, hashed)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
