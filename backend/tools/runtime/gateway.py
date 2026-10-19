"""Tool Gateway — the single invocation path (P1c-S2).

Everything the runtime promises about a tool call happens here and nowhere
else: timeout, retry (graded by side-effect strength), scope validation,
concurrency ceiling, error normalisation and tracing. Agents will call
``gateway.invoke(capability, payload)`` and never a tool function directly
(S3 migrates the nine existing call sites).

Two failure modes, deliberately different:

* **Contract violations raise** — an unregistered capability, or a scope the
  caller was not granted, is a programming/configuration error. Silently
  turning those into a failed ``ToolResult`` would hide a wiring bug behind
  "the tool failed", which is exactly the class of bug P0-W2 and D2' closed.
* **Runtime failures return** — timeouts and tool exceptions come back as
  ``ToolResult(ok=False, error=..., error_kind=...)`` so callers can degrade
  instead of crashing the node. The kind is data rather than a message
  format, because "the work never finished" and "the tool said no" call for
  different responses.

A third case has a channel of its own: a tool whose answer is neither success
nor failure — Ripple reporting that a simulation is still running, with the
``job_id`` needed to cancel or resume it — raises :class:`DomainOutcome`. That
arrives as ``ErrorKind.DOMAIN`` with the payload in ``ToolResult.domain``,
*returned*, not swallowed: it is an answer the caller must be able to read. It
is never retried, because asking again costs another simulation and cannot
change the answer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from backend.tools.runtime.account_gate import (
    AccountSlot,
    AccountSlotTimeoutError,
    acquire_account_slot,
)
from backend.tools.runtime.models import DomainOutcome, ErrorKind, ToolResult, ToolSpec
from backend.tools.runtime.registry import ToolRegistry

logger = logging.getLogger("xhs_growth.tools.gateway")

__all__ = [
    "PermissionDeniedError",
    "Sleeper",
    "ToolGateway",
    "TraceSink",
]

_ACCOUNT_PAYLOAD_KEY = "account_id"
"""Payload field that identifies the account a call acts for.

The gate key convention: with it, ``max_concurrency`` is a **per-account**
ceiling (``capability|account``); without it the ceiling stays per capability
(``capability``), which is what the old process-local semaphore did.
"""


def _gate_key(spec: ToolSpec, data: Mapping[str, Any]) -> str:
    """Slot-gate identity for one invocation (see ``_ACCOUNT_PAYLOAD_KEY``)."""
    account = str(data.get(_ACCOUNT_PAYLOAD_KEY) or "").strip()
    if account:
        return f"{spec.capability}|{account}"
    return spec.capability


TraceSink = Callable[[Mapping[str, Any]], Awaitable[None]]
"""Where Gateway trace events go (best-effort; never breaks a call).

Shape: ``{"kind": "tool", "capability", "thread_id", "ok", "attempts",
"elapsed_ms", "error", "error_kind", "domain_reason", "degraded",
"side_effect", "scopes"}``. S2 keeps this a plain callback so the runtime stays
free of a DB dependency; wiring it to the ``workflow_events`` tier happens where
a thread id exists.

``domain_reason`` is the machine-readable verdict only — not ``ToolResult.domain``.
That payload can hold prediction bodies, and the same rule as telemetry for
context recall applies: an event says what happened, the bodies belong behind
an explicit, sanitised export.

``scopes`` is ``"checked"`` / ``"unchecked"`` / ``"none"``, and it exists because
the scope check is *opt-in*: a capability that declares ``auth_scope`` is only
enforced when the caller passes ``granted_scopes``, and ``None`` reads as
"unchecked" rather than "denied". Without this field a decorative requirement
and a satisfied one look identical from the outside — which is how seven
scoped capabilities came to have no checked call site without anyone noticing.
It reports what happened to *this* call, not whether the capability is safe.
"""

Sleeper = Callable[[float], Awaitable[None]]
"""Injectable backoff sleep — tests pass a no-op to avoid real waiting."""


class PermissionDeniedError(PermissionError):
    """The caller was not granted every scope the capability requires."""

    def __init__(self, capability: str, missing: tuple[str, ...]) -> None:
        self.capability = capability
        self.missing = missing
        super().__init__(f"{capability}: missing required scope(s): {', '.join(missing)}")


def _value_degraded(value: Any) -> bool:
    """Let a tool report partial data through its own return value."""
    return isinstance(value, Mapping) and value.get("degraded") is True


def _scope_state(spec: ToolSpec, granted: tuple[str, ...] | None) -> str:
    """What actually happened to this call's requirement, for the trace.

    ``none`` means the capability declares no scope, so there was nothing to
    check; ``unchecked`` means it declares one and the caller passed no
    ``granted_scopes``; ``checked`` means the requirement was applied and
    satisfied (a violation raises before this point and never produces an
    event). Reported as data rather than a boolean because the interesting
    state is the *third* one: a requirement that exists and was skipped.
    """
    if not spec.auth_scope:
        return "none"
    return "unchecked" if granted is None else "checked"


class ToolGateway:
    """Invoke capabilities through one auditable path.

    ``registry`` supplies declarations and implementations; ``trace`` (if
    given) receives one event per invocation; ``sleeper`` is injectable so
    retry backoff is testable without real time passing.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        trace: TraceSink | None = None,
        sleeper: Sleeper | None = None,
    ) -> None:
        self._registry = registry
        self._trace = trace
        self._sleep: Sleeper = sleeper or asyncio.sleep

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    async def invoke(
        self,
        capability: str,
        payload: Mapping[str, Any] | None = None,
        *,
        thread_id: str = "",
        granted_scopes: tuple[str, ...] | None = None,
    ) -> ToolResult:
        """Run one capability. Raises on contract violations, returns on
        runtime failures (see module docstring)."""
        entry = self._registry.get(capability)  # raises UnknownCapabilityError
        spec = entry.spec
        data = dict(payload or {})
        self._check_scopes(spec, granted_scopes)
        scope_state = _scope_state(spec, granted_scopes)

        started = time.perf_counter()
        attempts = 0
        last_error = ""
        last_kind: ErrorKind | None = None
        slot: AccountSlot | None = None
        if spec.max_concurrency:
            try:
                slot = await acquire_account_slot(
                    key=_gate_key(spec, data),
                    limit=spec.max_concurrency,
                    wait_timeout_s=spec.effective_timeout_s,
                )
            except AccountSlotTimeoutError as exc:
                # The call never started — no side effect anywhere — so this
                # comes back as a plain timeout with ``attempts=0`` rather
                # than raising at the caller.
                return await self._finish(
                    spec,
                    ToolResult(
                        capability=capability,
                        ok=False,
                        error=str(exc),
                        error_kind=ErrorKind.TIMEOUT,
                        elapsed_ms=(time.perf_counter() - started) * 1000.0,
                        attempts=0,
                    ),
                    thread_id,
                    scope_state,
                )
        try:
            for attempt in range(1, spec.retry_policy.max_attempts + 1):
                attempts = attempt
                try:
                    value = await asyncio.wait_for(entry.fn(data), timeout=spec.effective_timeout_s)
                except DomainOutcome as exc:
                    # The tool has an answer, and the answer *is* the payload —
                    # so this returns immediately instead of joining the retry
                    # loop below. Re-asking would cost another simulation and
                    # cannot change a verdict that has already been reached.
                    return await self._finish(
                        spec,
                        ToolResult(
                            capability=capability,
                            ok=False,
                            error=f"domain outcome: {exc.reason}",
                            error_kind=ErrorKind.DOMAIN,
                            domain=dict(exc.payload),
                            elapsed_ms=(time.perf_counter() - started) * 1000.0,
                            attempts=attempts,
                        ),
                        thread_id,
                        scope_state,
                    )
                except TimeoutError:
                    last_error = f"timeout after {spec.effective_timeout_s:g}s"
                    last_kind = ErrorKind.TIMEOUT
                except Exception as exc:  # tool failure → normalised, not raised
                    last_error = f"{type(exc).__name__}: {exc}"
                    last_kind = ErrorKind.EXCEPTION
                else:
                    return await self._finish(
                        spec,
                        ToolResult(
                            capability=capability,
                            ok=True,
                            value=value,
                            elapsed_ms=(time.perf_counter() - started) * 1000.0,
                            attempts=attempts,
                            degraded=attempts > 1 or _value_degraded(value),
                        ),
                        thread_id,
                        scope_state,
                    )

                if attempt < spec.retry_policy.max_attempts:
                    if spec.retry_policy.requires_idempotency_key and not data.get(
                        "idempotency_key"
                    ):
                        # Refusing to retry a write without a key is the whole
                        # point of the flag — say so instead of silently
                        # repeating a side effect.
                        last_error += " (not retried: no idempotency_key in payload)"
                        break
                    if spec.retry_policy.backoff_s:
                        await self._sleep(spec.retry_policy.backoff_s)

            return await self._finish(
                spec,
                ToolResult(
                    capability=capability,
                    ok=False,
                    error=last_error,
                    error_kind=last_kind,
                    elapsed_ms=(time.perf_counter() - started) * 1000.0,
                    attempts=attempts,
                ),
                thread_id,
                scope_state,
            )
        finally:
            if slot is not None:
                await slot.release()

    def _check_scopes(self, spec: ToolSpec, granted: tuple[str, ...] | None) -> None:
        """No ``granted_scopes`` means "not checked here" (S3+ passes them)."""
        if granted is None or not spec.auth_scope:
            return
        missing = tuple(scope for scope in spec.auth_scope if scope not in granted)
        if missing:
            raise PermissionDeniedError(spec.capability, missing)

    async def _finish(
        self, spec: ToolSpec, result: ToolResult, thread_id: str, scope_state: str
    ) -> ToolResult:
        """Emit the trace event (best-effort) and hand the result back."""
        if self._trace is not None:
            event = {
                "kind": "tool",
                "event": "invoke",
                "capability": spec.capability,
                "side_effect": spec.side_effect.value,
                "thread_id": thread_id,
                "ok": result.ok,
                "attempts": result.attempts,
                "elapsed_ms": round(result.elapsed_ms, 3),
                "error": result.error,
                "error_kind": result.error_kind.value if result.error_kind is not None else "",
                "domain_reason": str(result.domain.get("reason", "")),
                "degraded": result.degraded,
                "scopes": scope_state,
            }
            try:
                await self._trace(event)
            except Exception as exc:  # telemetry must never break a call
                logger.debug("gateway trace emission failed: %s", exc)
        return result
