import pyotp

from app.auth.models import User
from app.core.crypto import decrypt, encrypt

ISSUER = "MegooColab"


def start_setup(user: User) -> tuple[str, str]:
    """Stores a new (not yet enabled) secret; returns (secret, otpauth_uri)."""
    secret = pyotp.random_base32()
    user.totp_secret_enc = encrypt(secret)
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=ISSUER)
    return secret, uri


def verify(user: User, code: str | None) -> bool:
    if not code or not user.totp_secret_enc:
        return False
    return pyotp.TOTP(decrypt(user.totp_secret_enc)).verify(code.strip(), valid_window=1)
