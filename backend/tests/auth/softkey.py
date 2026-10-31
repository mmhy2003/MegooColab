"""A software passkey for tests: it answers WebAuthn options the way a browser's authenticator would."""

import hashlib
import json
import os
import struct

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url


def _b64(data: bytes) -> str:
    return bytes_to_base64url(data)


class SoftKey:
    """One credential (ES256, attestation "none"), with its own signature counter."""

    def __init__(self, origin: str = "http://localhost:8080", rp_id: str = "localhost") -> None:
        self.origin = origin
        self.rp_id = rp_id
        self.credential_id = os.urandom(16)
        self._key = ec.generate_private_key(ec.SECP256R1())
        self._counter = 0

    def _client_data(self, kind: str, options: dict) -> bytes:
        return json.dumps(
            {"type": kind, "challenge": options["challenge"], "origin": self.origin, "crossOrigin": False}
        ).encode()

    def _auth_data(self, flags: int, counter: int, attested: bytes = b"") -> bytes:
        return hashlib.sha256(self.rp_id.encode()).digest() + bytes([flags]) + struct.pack(">I", counter) + attested

    def register(self, options: dict) -> dict:
        """A PublicKeyCredential JSON for navigator.credentials.create(options)."""
        numbers = self._key.public_key().public_numbers()
        cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})
        attested = bytes(16) + struct.pack(">H", len(self.credential_id)) + self.credential_id + cose
        auth_data = self._auth_data(0x01 | 0x04 | 0x40, 0, attested)
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        cid = _b64(self.credential_id)
        return {
            "id": cid, "rawId": cid, "type": "public-key",
            "response": {
                "clientDataJSON": _b64(self._client_data("webauthn.create", options)),
                "attestationObject": _b64(attestation),
                "transports": ["internal"],
            },
            "clientExtensionResults": {},
        }

    def sign(self, options: dict, *, sign_count: int | None = None) -> dict:
        """An assertion JSON for navigator.credentials.get(options); the counter goes up unless given."""
        if sign_count is None:
            self._counter += 1
            sign_count = self._counter
        auth_data = self._auth_data(0x01 | 0x04, sign_count)
        client_data = self._client_data("webauthn.get", options)
        signature = self._key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        cid = _b64(self.credential_id)
        return {
            "id": cid, "rawId": cid, "type": "public-key",
            "response": {
                "clientDataJSON": _b64(client_data),
                "authenticatorData": _b64(auth_data),
                "signature": _b64(signature),
                "userHandle": None,
            },
            "clientExtensionResults": {},
        }


__all__ = ["SoftKey", "base64url_to_bytes"]
