from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SecretBox:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("SecretBox requires a 32-byte key.")
        self._aesgcm = AESGCM(key)

    def encrypt(self, plaintext: str) -> str:
        nonce = os.urandom(12)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext.encode("utf-8"), b"tg-detox-locker")
        return "v1:" + base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")

    def decrypt(self, sealed: str) -> str:
        version, encoded = sealed.split(":", 1)
        if version != "v1":
            raise ValueError("Unsupported secret version.")
        raw = base64.urlsafe_b64decode(encoded.encode("ascii"))
        nonce, ciphertext = raw[:12], raw[12:]
        plaintext = self._aesgcm.decrypt(nonce, ciphertext, b"tg-detox-locker")
        return plaintext.decode("utf-8")
