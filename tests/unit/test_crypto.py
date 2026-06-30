"""Tests for Fernet crypto module."""

from __future__ import annotations

import os

from backend.db.crypto import decrypt_value, encrypt_value, generate_key, mask_value


def test_encrypt_decrypt_roundtrip():
    """Encrypt then decrypt should return original value."""
    os.environ["ENCRYPTION_KEY"] = generate_key()
    # Reset module-level fernet so it picks up the new key
    import backend.db.crypto as crypto_mod

    crypto_mod._fernet = None

    plain = "sk-ant-api03-1234567890abcdef"
    encrypted = encrypt_value(plain)
    assert decrypt_value(encrypted) == plain


def test_mask_value():
    assert mask_value("sk-ant-api03-1234567890abcdef") == "sk-a...cdef"
    assert mask_value("short") == "***"


def test_plaintext_fallback():
    """Without ENCRYPTION_KEY, values stored as plaintext UTF-8."""
    os.environ.pop("ENCRYPTION_KEY", None)
    import backend.db.crypto as crypto_mod

    crypto_mod._fernet = None

    plain = "my-secret-key"
    encrypted = encrypt_value(plain)
    assert decrypt_value(encrypted) == plain


def test_generate_key():
    key = generate_key()
    assert isinstance(key, str)
    assert len(key) > 0
    # Key should be valid Fernet key (base64-encoded 32 bytes)
    from cryptography.fernet import Fernet

    Fernet(key.encode())  # Should not raise


if __name__ == "__main__":
    test_encrypt_decrypt_roundtrip()
    test_mask_value()
    test_plaintext_fallback()
    test_generate_key()
    print("All crypto tests passed")
