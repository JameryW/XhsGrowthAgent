"""Fernet-based encryption for account credentials.

Uses ENCRYPTION_KEY env var. Falls back to plaintext with a warning if missing.
"""

from __future__ import annotations

import logging
import os
from typing import Any, cast

logger = logging.getLogger("xhs_growth.db.crypto")

_fernet: Any = None


def _init_fernet() -> Any:
    global _fernet
    key = os.environ.get("ENCRYPTION_KEY", "")
    if not key:
        logger.warning("ENCRYPTION_KEY not set — credentials stored as plaintext")
        return None
    try:
        from cryptography.fernet import Fernet

        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
        return _fernet
    except Exception as e:
        logger.warning(f"ENCRYPTION_KEY invalid ({e}) — credentials stored as plaintext")
        return None


def encrypt_value(plain: str) -> bytes:
    """Encrypt a string value. Returns bytes (Fernet) or UTF-8 bytes (plaintext fallback)."""
    global _fernet
    if _fernet is None:
        _fernet = _init_fernet()
    if _fernet is not None:
        return cast("bytes", _fernet.encrypt(plain.encode()))
    return plain.encode()


def decrypt_value(data: bytes) -> str:
    """Decrypt bytes to string. Handles both Fernet tokens and plaintext UTF-8."""
    global _fernet
    if _fernet is None:
        _fernet = _init_fernet()
    if _fernet is not None:
        try:
            return cast("str", _fernet.decrypt(data).decode())
        except Exception:
            # Might be plaintext from before ENCRYPTION_KEY was set
            return data.decode()
    return data.decode()


def generate_key() -> str:
    """Generate a new Fernet key (for setup scripts)."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


def mask_value(value: str) -> str:
    """Mask a secret for display: show first 4 and last 4 chars."""
    if len(value) <= 12:
        return "***"
    return value[:4] + "..." + value[-4:]
