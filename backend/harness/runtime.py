"""Runtime policy injection for the harness (P3/E2): decide once, read everywhere.

:mod:`backend.harness.policy` defines *what* a harness variant may change; this
module owns *which* policy the running process uses.  The production call sites
that make those decisions (the model router, the context compiler and the tool
gateway) read :func:`get_policy`, so an injected variant takes effect in all of
them while the default policy keeps today's behaviour exactly.

Resolution order, highest first:

1. a policy passed to :func:`configure_policy` (also how tests inject a fake);
2. ``XHS_HARNESS_POLICY`` — ``"module:factory"`` — imported lazily on the first
   read and cached, so deployment can select a variant without touching code;
3. :class:`~backend.harness.policy.DefaultHarnessPolicy` (today's behaviour).

An unreadable or invalid environment spec raises :class:`HarnessPolicyLoadError`
(a ``ValueError``/``RuntimeError``) instead of silently falling back: a typo in
the deployment config must fail loudly, not quietly run the baseline.

Every policy change bumps a generation counter (:func:`policy_generation`).
Callers that cache decisions derived from the policy — the router's model cache
is the one today — include it in their cache key, so configuring or resetting a
policy can never serve a model built from the previous policy.
"""

from __future__ import annotations

import importlib
import os
import threading
from typing import Any

from backend.harness.policy import DefaultHarnessPolicy, HarnessPolicy, default_policy

__all__ = [
    "ENV_POLICY_VAR",
    "HarnessPolicyLoadError",
    "configure_policy",
    "get_policy",
    "is_default_policy",
    "load_policy",
    "policy_generation",
    "reset_policy",
]

ENV_POLICY_VAR = "XHS_HARNESS_POLICY"
"""Environment variable naming the variant policy as ``"module:factory"``."""

_lock = threading.RLock()
_default: HarnessPolicy = default_policy()
_explicit: HarnessPolicy | None = None
_env_policy: HarnessPolicy | None = None
_env_loaded = False
_generation = 0


class HarnessPolicyLoadError(ValueError, RuntimeError):
    """A ``XHS_HARNESS_POLICY`` spec could not be resolved to a policy.

    Subclasses both ``ValueError`` (bad spec) and ``RuntimeError`` (deployment
    configuration failure) so either ``except`` reaches it.
    """


def load_policy(spec: str) -> HarnessPolicy:
    """Import ``"module:factory"`` and return the policy it names.

    ``factory`` is called when it is callable, otherwise it is used as-is
    (a module-level policy instance is a valid target).  The result must
    satisfy the runtime-checkable :class:`HarnessPolicy` protocol.
    """
    module_name, separator, attribute_path = spec.partition(":")
    module_name, attribute_path = module_name.strip(), attribute_path.strip()
    if not separator or not module_name or not attribute_path:
        raise HarnessPolicyLoadError(
            f"harness policy spec {spec!r} must look like 'module:factory'"
        )
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # surfaced as a config error, not an import crash
        raise HarnessPolicyLoadError(
            f"cannot import harness policy module {module_name!r} (from spec {spec!r}): {exc}"
        ) from exc
    target: Any = module
    try:
        for part in attribute_path.split("."):
            target = getattr(target, part)
    except AttributeError as exc:
        raise HarnessPolicyLoadError(
            f"harness policy spec {spec!r}: module {module_name!r} has no "
            f"attribute {attribute_path!r}"
        ) from exc
    if callable(target):
        try:
            policy = target()
        except Exception as exc:  # a factory that cannot build a policy is a config error
            raise HarnessPolicyLoadError(
                f"harness policy factory {spec!r} raised {type(exc).__name__}: {exc}"
            ) from exc
    else:
        policy = target
    if not isinstance(policy, HarnessPolicy):
        raise HarnessPolicyLoadError(
            f"harness policy {spec!r} resolved to {type(policy).__name__}, "
            "which does not implement the HarnessPolicy protocol"
        )
    return policy


def _load_from_env() -> HarnessPolicy | None:
    """Read ``XHS_HARNESS_POLICY`` once; ``None`` means "no variant configured"."""
    spec = os.environ.get(ENV_POLICY_VAR, "").strip()
    if not spec:
        return None
    return load_policy(spec)


def configure_policy(policy: HarnessPolicy | None) -> None:
    """Use ``policy`` for this process; ``None`` removes the explicit override.

    With ``None`` the next :func:`get_policy` falls back to the environment (and
    finally the default policy), which is what "unset the variant" means.
    """
    global _explicit, _generation
    with _lock:
        _explicit = policy
        _generation += 1


def reset_policy() -> None:
    """Forget every configured policy; the next read resolves from scratch.

    This also forgets the cached environment result, so a test that changes
    ``XHS_HARNESS_POLICY`` (or production that rotates it before the first
    decision) is not stuck with the previous import.
    """
    global _explicit, _env_loaded, _env_policy, _generation
    with _lock:
        _explicit = None
        _env_policy = None
        _env_loaded = False
        _generation += 1


def get_policy() -> HarnessPolicy:
    """The policy in effect right now (explicit override → env → default)."""
    global _env_loaded, _env_policy
    with _lock:
        if _explicit is not None:
            return _explicit
        if not _env_loaded:
            # Assignment happens only on success, so a broken env spec raises on
            # every read instead of being cached as "no policy".
            _env_policy = _load_from_env()
            _env_loaded = True
        if _env_policy is not None:
            return _env_policy
        return _default


def policy_generation() -> int:
    """Monotonic counter bumped by every :func:`configure_policy`/``reset_policy``.

    Cache keys derived from policy decisions must include it; two equal
    generations mean "same policy", not "same decisions" only when the policy
    object's behaviour is itself immutable.
    """
    with _lock:
        return _generation


def is_default_policy(policy: HarnessPolicy) -> bool:
    """Whether ``policy`` *is* the default implementation (exact type check).

    Deliberately not ``isinstance``: a variant may subclass
    ``DefaultHarnessPolicy`` and override one decision, and that variant must
    take the variant code path.  Call sites use this to keep the default path
    byte-identical — notably the tool gateway, which must keep trusting a custom
    registry's own declarations rather than looking them up in the production
    catalogue.
    """
    return type(policy) is DefaultHarnessPolicy
