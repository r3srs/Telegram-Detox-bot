from __future__ import annotations

import os

import pytest
from cryptography.exceptions import InvalidTag

from tg_detox_locker.crypto import SecretBox


def test_secret_box_round_trip() -> None:
    box = SecretBox(os.urandom(32))
    sealed = box.encrypt("secret")
    assert box.decrypt(sealed) == "secret"


def test_secret_box_rejects_wrong_key() -> None:
    source = SecretBox(os.urandom(32))
    sealed = source.encrypt("secret")
    with pytest.raises(InvalidTag):
        SecretBox(os.urandom(32)).decrypt(sealed)
