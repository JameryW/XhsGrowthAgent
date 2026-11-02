"""Fixture schema and the single redaction pass for Adaptive Harness evaluation (E1).

The evaluation corpus is built from **real** workflow checkpoints (decision
2026-11-01), so the on-disk fixture is a *redacted* projection of a real state and
never the raw one.  Extraction, validation and the unit tests all go through this
module: one redaction implementation means a field cannot be scrubbed on one path
while leaking on another.

What a fixture may contain:

* workflow state values needed by a decision replay (phase, copy/visual/plan
  structures, policy inputs);
* stable pseudonyms for identities, and blanked values where a pseudonym would
  still be revealing (URLs, profile links).

What it never contains: cookies/tokens/secrets, CDP endpoints, profile paths,
``messages`` (raw model output), URLs, or absolute filesystem paths.  The
``RedactionReport`` counts every category so a fixture states what was removed
instead of asking the reader to trust it.

The corpus is still sensitive in one respect: pseudonyms are deterministic
truncated hashes, and short user-chosen ids (an account called ``my_account``)
can be recovered by dictionary attack.  Treat ``.eval-fixtures/`` as private
data; the module removes plaintext, not the possibility of guessing it.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "2"
REDACTION_VERSION = "2"
EXTRACTOR_VERSION = "2"

# kind prefix used in the pseudonym, so an operator can tell what a redacted value
# used to be without being able to recover it.
_IDENTIFIER_KEYS: dict[str, str] = {
    "account_id": "acct",
    "thread_id": "thread",
    # PublishResult carries the raw thread id as workflow_thread_id; leaving it
    # out of this table would copy the one value the pseudonym is meant to hide.
    "workflow_thread_id": "thread",
    "session_id": "session",
    "creator_id": "creator",
    "creator_nickname": "creator",
    "nickname": "creator",
    "author": "creator",
    "audience_id": "audience",
    "owner_user_id": "user",
    "user_id": "user",
    "approved_by": "user",
    "reviewer": "user",
    "post_id": "post",
    "note_id": "post",
}
_SECRET_KEY_FRAGMENTS = (
    "cookie",
    "web_session",
    "token",
    "api_key",
    "secret",
    "password",
    "authorization",
    "proxy",
    "credential",
)
_LOCATION_KEYS = frozenset(
    {
        "cdp_endpoint",
        "chrome_profile_path",
        "chrome_profile",
    }
)
# Identity-bearing links (profile pages, post pages, avatars, covers) are not
# pseudonymised: a URL that still resolves is a leak even with a fake host.
_URL_KEY_SUFFIXES = ("_url", "url", "_link", "link", "_uri", "uri")
_PATH_LIST_KEYS = frozenset({"image_paths", "images", "generated_images", "image_urls"})
_PATH_KEY_SUFFIXES = ("_path", "_image", "_images", "_paths", "path")
_DROP_KEYS = frozenset({"messages"})
_ABSOLUTE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|/(?:Users|home|tmp|var|opt|root|mnt)/)")
_MAX_DEPTH = 12


class RedactionReport(BaseModel):
    """What the redaction pass changed, by category (counted, not described)."""

    identifiers: int = 0
    secrets: int = 0
    locations: int = 0
    paths: int = 0
    dropped_keys: int = 0


class EvalFixture(BaseModel):
    """One redacted checkpoint state, self-describing enough to replay offline."""

    schema_version: str = SCHEMA_VERSION
    fixture_id: str = Field(min_length=1)
    source: Literal["sqlite", "postgres"]
    thread_pseudonym: str = Field(min_length=1)
    checkpoint_id: str = Field(default="", max_length=128)
    phase: str = ""
    state_sha256: str = Field(min_length=64, max_length=64)
    redactions: RedactionReport
    state: dict[str, Any]


class FixtureEntry(BaseModel):
    fixture_id: str
    file: str
    sha256: str = Field(min_length=64, max_length=64)
    phase: str = ""
    thread_pseudonym: str


class FixtureManifest(BaseModel):
    """Provenance for a corpus directory: counts and hashes, no state values."""

    schema_version: str = SCHEMA_VERSION
    extractor_version: str = EXTRACTOR_VERSION
    redaction_version: str = REDACTION_VERSION
    source_kind: Literal["sqlite", "postgres"]
    generated_at: str
    total: int = 0
    fixtures: list[FixtureEntry] = Field(default_factory=list)
    skipped: dict[str, int] = Field(default_factory=dict)
    # "hmac" means pseudonyms were keyed with a deployment secret; "sha256" means
    # they are a plain truncated hash and short ids are dictionary-attackable.
    pseudonym_mode: Literal["sha256", "hmac"] = "sha256"


def pseudonym(kind: str, value: str, key: bytes | None = None) -> str:
    """A stable one-way handle for *value*: ``<kind>_<digest[:12]>``.

    With ``key`` the digest is an HMAC-SHA256, so an attacker holding only the
    corpus cannot guess short account ids by hashing candidates.  Without a key it
    falls back to a plain truncated SHA-256 (kept for compatibility); the manifest
    records which mode produced a corpus, and the extractor warns on the weak one.
    Stable in both modes so fixtures stay comparable across runs of the same key.
    """
    message = f"{kind}:{value}".encode()
    if key is None:
        digest = hashlib.sha256(message).hexdigest()[:12]
    else:
        digest = hmac.new(key, message, hashlib.sha256).hexdigest()[:12]
    return f"{kind}_{digest}"


def state_sha256(state: Mapping[str, Any]) -> str:
    """Hash of the redacted state's canonical JSON — the fixture's identity."""
    import json

    canonical = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _extension_of(value: str) -> str:
    leaf = value.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." not in leaf:
        return "bin"
    suffix = leaf.rsplit(".", 1)[-1].lower()
    if len(suffix) > 5 or not suffix.isalnum():
        return "bin"
    return suffix


def _sanitize_path_list(values: Sequence[Any], counter: list[int]) -> list[str]:
    sanitized: list[str] = []
    for index, value in enumerate(values):
        if not isinstance(value, str) or not value:
            continue
        sanitized.append(f"image/{index:02d}.{_extension_of(value)}")
        counter[0] += 1
    return sanitized


def _is_path_key(key: str) -> bool:
    lowered = key.lower()
    return key in _PATH_LIST_KEYS or lowered.endswith(_PATH_KEY_SUFFIXES)


def _is_url_key(key: str) -> bool:
    return key.lower().endswith(_URL_KEY_SUFFIXES)


def redact_state(
    value: Any,
    *,
    redaction_key: bytes | None = None,
    _depth: int = 0,
) -> tuple[Any, RedactionReport]:
    """Return a redacted deep copy of *value* plus what was changed.

    Deterministic: the same input always produces the same output, so a fixture
    hash is a real identity.  Raises ``ValueError`` on a non-JSON-like shape (a
    checkpoint containing something else is not a state we can replay).
    """
    if _depth > _MAX_DEPTH:
        raise ValueError(f"state nesting deeper than {_MAX_DEPTH}; refusing to redact")
    report = RedactionReport()

    def walk(node: Any, depth: int) -> Any:
        if depth > _MAX_DEPTH:
            raise ValueError(f"state nesting deeper than {_MAX_DEPTH}; refusing to redact")
        if isinstance(node, Mapping):
            out: dict[str, Any] = {}
            for raw_key, raw_value in node.items():
                key = str(raw_key)
                if key in _DROP_KEYS:
                    # Raw model output can quote the account, the reviewer or the
                    # source material verbatim; a fixture never needs it.
                    report.dropped_keys += 1
                    continue
                if key in _LOCATION_KEYS:
                    report.locations += 1
                    out[key] = ""
                    continue
                if key in _IDENTIFIER_KEYS:
                    kind = _IDENTIFIER_KEYS[key]
                    if isinstance(raw_value, str) and raw_value.strip():
                        report.identifiers += 1
                        out[key] = pseudonym(kind, raw_value.strip(), redaction_key)
                    elif (
                        isinstance(raw_value, (list, tuple))
                        and raw_value
                        and all(isinstance(item, str) and item.strip() for item in raw_value)
                    ):
                        report.identifiers += 1
                        out[key] = [
                            pseudonym(kind, item.strip(), redaction_key) for item in raw_value
                        ]
                    else:
                        if raw_value not in (None, "", [], ()):
                            report.identifiers += 1
                        out[key] = ""
                    continue
                is_secret_key = any(fragment in key.lower() for fragment in _SECRET_KEY_FRAGMENTS)
                if is_secret_key:
                    # Scalar or container: a secret-shaped key never carries its
                    # value through.  Walking a container instead would keep
                    # ``{"api_key": {"value": "sk-..."}}`` — the inner key is
                    # innocent, so the redaction has to stop at the outer one.
                    report.secrets += 1
                    out[key] = ""
                    continue
                if _is_url_key(key):
                    report.locations += 1
                    out[key] = ""
                    continue
                if _is_path_key(key):
                    counter = [0]
                    if isinstance(raw_value, str) and raw_value:
                        out[key] = f"image/00.{_extension_of(raw_value)}"
                        counter[0] += 1
                    elif isinstance(raw_value, (list, tuple)):
                        out[key] = _sanitize_path_list(raw_value, counter)
                    else:
                        out[key] = ""
                    report.paths += counter[0]
                    continue
                out[key] = walk(raw_value, depth + 1)
            return out
        if isinstance(node, (list, tuple)):
            return [walk(item, depth + 1) for item in node]
        if isinstance(node, str):
            if _ABSOLUTE_PATH.match(node):
                report.locations += 1
                return ""
            return node
        if isinstance(node, (int, float, bool)) or node is None:
            return node
        raise ValueError(f"state contains a non-JSON value of type {type(node).__name__}")

    return walk(value, _depth), report


def build_fixture(
    *,
    source: Literal["sqlite", "postgres"],
    thread_id: str,
    checkpoint_id: str,
    state: Mapping[str, Any],
    redaction_key: bytes | None = None,
) -> EvalFixture:
    """Redact one checkpoint state into a fixture (pure; no I/O)."""
    redacted, report = redact_state(state, redaction_key=redaction_key)
    assert isinstance(redacted, dict)
    thread_pseudonym = pseudonym("thread", thread_id, redaction_key)
    fixture_id = f"{thread_pseudonym}-{checkpoint_id[:8] or 'latest'}"
    phase = str(redacted.get("phase") or "")
    return EvalFixture(
        fixture_id=fixture_id,
        source=source,
        thread_pseudonym=thread_pseudonym,
        checkpoint_id=checkpoint_id[:128],
        phase=phase,
        state_sha256=state_sha256(redacted),
        redactions=report,
        state=redacted,
    )
