"""L1 decision replay (P3/E3): does a variant decide the same on real states?

``docs/adaptive-harness-eval-plan.md`` §3 defines L1 as: replay recorded
state/context fixtures and assert the variant's decisions (model routing,
context budget, escalation) match the expected ones.  Its judging rule (§3 and
§4) is two-tier — rules marked *mandatory* must match 100%, *preference*
differences are allowed but must be reported.

This module implements that rule against the four decisions ``HarnessPolicy``
owns.  The **expected side is the baseline policy** (``DefaultHarnessPolicy``,
i.e. today's code paths) plus the mandatory invariants below.  It is deliberately
not a hand-written golden file: a duplicated golden would drift the day routing
legitimately changes (see #756), and then the gate would fail on correct code.
A variant is asked to replace the baseline, so "did it decide differently on
these states?" is exactly the comparison worth reporting.

Mandatory (red on violation, for the baseline and the variant alike):

* every ``TaskType`` answers with a non-blank model id;
* every context budget is ``None`` or a non-negative int (``bool`` is not an int
  here — ``True`` is not a budget);
* escalation targets are non-blank, duplicate-free model ids;
* tool limits keep the catalogue shape (capability matches its key,
  ``max_concurrency`` is ``None`` or int ``>= 0``, ``timeout_s`` is ``None`` or
  positive);
* the replay is deterministic: two passes over the same fixtures agree.

Preference (reported, never red by itself): any decision that differs from the
baseline on a given fixture.  The diff is keyed by fixture id and names the field
that moved, so a reviewer sees which recorded state changed which decision —
that is the evidence an A/B gate exists to produce.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from fixtures import EvalFixture, FixtureManifest

_EVAL_STATUS = Literal["pass", "red", "skip"]


@dataclass(frozen=True)
class DecisionRecord:
    """The four decisions, replayed for one fixture."""

    fixture_id: str
    phase: str
    models: dict[str, str]
    context_budget: int | None
    escalation: dict[str, tuple[str, ...]]
    tool_limits: dict[str, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "phase": self.phase,
            "models": dict(self.models),
            "context_budget": self.context_budget,
            "escalation": {task: list(targets) for task, targets in self.escalation.items()},
            "tool_limits": {cap: dict(entry) for cap, entry in self.tool_limits.items()},
        }


@dataclass(frozen=True)
class ReplayOutcome:
    """What the L1 check found: a gate status, a sentence, and the preference diff."""

    status: _EVAL_STATUS
    detail: str
    fixtures: int = 0
    diff: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "fixtures": self.fixtures,
            "fixtures_with_preference_diff": len(self.diff),
            "diff": self.diff,
        }


@lru_cache(maxsize=1)
def _capabilities() -> tuple[str, ...]:
    """The production catalogue's capability names (the same list E3 snapshots)."""
    from backend.tools.runtime.catalog import build_registry

    return tuple(build_registry().capabilities())


def _limit_entry(policy: Any, capability: str) -> dict[str, Any]:
    """Normalise one ``ToolLimits`` into plain JSON-able fields (tolerant of fakes)."""
    entry = policy.tool_limits(capability)
    if isinstance(entry, dict):
        return {
            "capability": entry.get("capability"),
            "max_concurrency": entry.get("max_concurrency"),
            "timeout_s": entry.get("timeout_s"),
        }
    return {
        "capability": getattr(entry, "capability", None),
        "max_concurrency": getattr(entry, "max_concurrency", None),
        "timeout_s": getattr(entry, "timeout_s", None),
    }


def replay_policy(
    policy: Any,
    fixtures: Sequence[EvalFixture],
    *,
    capabilities: Sequence[str] | None = None,
) -> list[DecisionRecord]:
    """Replay the four policy decisions on every fixture (rain or shine)."""
    from backend.config.models import TaskType

    caps = tuple(capabilities) if capabilities is not None else _capabilities()
    records: list[DecisionRecord] = []
    for fixture in fixtures:
        phase = fixture.phase or str(fixture.state.get("phase") or "")
        records.append(
            DecisionRecord(
                fixture_id=fixture.fixture_id,
                phase=phase,
                models={task.value: policy.route_model(task) for task in TaskType},
                context_budget=policy.context_budget(phase=phase),
                escalation={
                    task.value: tuple(policy.escalation_targets(task)) for task in TaskType
                },
                tool_limits={cap: _limit_entry(policy, cap) for cap in caps},
            )
        )
    return records


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def mandatory_problems(records: Sequence[DecisionRecord]) -> list[str]:
    """Every hard rule an L1 record must satisfy; empty list means clean."""
    from backend.config.models import TaskType

    problems: list[str] = []
    for record in records:
        if not record.fixture_id:
            problems.append("a replay record has no fixture id")
        for task in TaskType:
            model = record.models.get(task.value)
            if not isinstance(model, str) or not model.strip():
                problems.append(f"{record.fixture_id}: no model id for {task.value}")
        budget = record.context_budget
        if budget is not None and (not _is_int(budget) or budget < 0):
            problems.append(f"{record.fixture_id}: context budget {budget!r} is not None/int>=0")
        for task in TaskType:
            targets = record.escalation.get(task.value)
            if not isinstance(targets, tuple):
                problems.append(f"{record.fixture_id}: escalation[{task.value}] is not a tuple")
                continue
            if any(not isinstance(target, str) or not target.strip() for target in targets):
                problems.append(f"{record.fixture_id}: escalation[{task.value}] has blank targets")
            if len(set(targets)) != len(targets):
                problems.append(f"{record.fixture_id}: escalation[{task.value}] repeats a target")
        for capability, entry in record.tool_limits.items():
            if not isinstance(entry, dict):
                problems.append(f"{record.fixture_id}: tool limit {capability} is not a mapping")
                continue
            if entry.get("capability") != capability:
                problems.append(f"{record.fixture_id}: tool limit {capability} names another id")
            concurrency = entry.get("max_concurrency")
            if concurrency is not None and (not _is_int(concurrency) or concurrency < 0):
                problems.append(f"{record.fixture_id}: {capability} max_concurrency is invalid")
            timeout = entry.get("timeout_s")
            if timeout is not None and (
                isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0
            ):
                problems.append(f"{record.fixture_id}: {capability} timeout_s is not positive")
        try:
            json.dumps(record.to_dict())
        except TypeError as exc:
            problems.append(f"{record.fixture_id}: decisions are not JSON-able ({exc})")
    return problems


def _changed(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Per-key ``baseline -> current`` for two decision mappings."""
    changed: dict[str, Any] = {}
    for key in sorted(set(baseline) | set(current)):
        before, after = baseline.get(key), current.get(key)
        if before != after:
            changed[key] = {"baseline": _jsonable(before), "current": _jsonable(after)}
    return changed


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def diff_records(
    baseline: Sequence[DecisionRecord], current: Sequence[DecisionRecord]
) -> dict[str, Any]:
    """Preference diff: only fixtures whose decisions moved, only the fields that did."""
    by_id = {record.fixture_id: record for record in baseline}
    diff: dict[str, Any] = {}
    for record in current:
        base = by_id.get(record.fixture_id)
        if base is None:
            diff[record.fixture_id] = {"fixture": {"baseline": None, "current": "not in baseline"}}
            continue
        moved: dict[str, Any] = {}
        if base.phase != record.phase:
            moved["phase"] = {"baseline": base.phase, "current": record.phase}
        if base.context_budget != record.context_budget:
            moved["context_budget"] = {
                "baseline": base.context_budget,
                "current": record.context_budget,
            }
        for name in ("models", "escalation", "tool_limits"):
            before = {key: _jsonable(item) for key, item in getattr(base, name).items()}
            after = {key: _jsonable(item) for key, item in getattr(record, name).items()}
            changes = _changed(before, after)
            if changes:
                moved[name] = changes
        if moved:
            diff[record.fixture_id] = moved
    missing = sorted(set(by_id) - {record.fixture_id for record in current})
    if missing:
        diff["<missing fixtures>"] = {"baseline": missing, "current": None}
    return diff


def load_fixtures(corpus_dir: Path) -> list[EvalFixture]:
    """Read every fixture the manifest lists (hash/schema validity belongs to the corpus check)."""
    manifest = FixtureManifest.model_validate_json((corpus_dir / "manifest.json").read_bytes())
    fixtures: list[EvalFixture] = []
    for entry in manifest.fixtures:
        payload = (corpus_dir / entry.file).read_bytes()
        fixtures.append(EvalFixture.model_validate_json(payload))
    return fixtures


def run_l1_replay(
    policy: Any,
    corpus_dir: Path,
    *,
    baseline_policy: Any | None = None,
    variant: bool = False,
    capabilities: Sequence[str] | None = None,
) -> ReplayOutcome:
    """Run the L1 check: invariants, determinism, then the baseline preference diff."""
    if not corpus_dir.is_dir():
        return ReplayOutcome(
            status="skip",
            detail=(
                f"{corpus_dir} not found: run scripts/eval/extract_fixtures.py first "
                "(or pass --corpus); a missing corpus is a gap, not a pass"
            ),
        )
    try:
        fixtures = load_fixtures(corpus_dir)
    except (OSError, ValueError) as exc:
        return ReplayOutcome(status="red", detail=f"corpus could not be replayed: {exc}")
    if not fixtures:
        return ReplayOutcome(
            status="skip",
            detail="corpus lists 0 fixtures: nothing to replay (the corpus check reds it)",
        )

    from backend.harness.policy import DefaultHarnessPolicy

    baseline = baseline_policy if baseline_policy is not None else DefaultHarnessPolicy()
    caps = tuple(capabilities) if capabilities is not None else _capabilities()

    first = replay_policy(policy, fixtures, capabilities=caps)
    second = replay_policy(policy, fixtures, capabilities=caps)
    if first != second:
        return ReplayOutcome(
            status="red",
            detail="replay is not deterministic: two passes over the same fixtures disagree",
            fixtures=len(fixtures),
        )

    problems = mandatory_problems(first)
    if problems:
        return ReplayOutcome(
            status="red",
            detail="mandatory rules broken: " + "; ".join(problems[:5]),
            fixtures=len(fixtures),
        )

    diff = diff_records(replay_policy(baseline, fixtures, capabilities=caps), first)
    if diff and not variant:
        return ReplayOutcome(
            status="red",
            detail=(
                "a policy that is not the baseline (no --variant) changed "
                f"{len(diff)} fixture(s); the baseline replay must be decision-identical"
            ),
            fixtures=len(fixtures),
            diff=diff,
        )
    if diff:
        return ReplayOutcome(
            status="pass",
            detail=(
                f"{len(fixtures)} fixtures replayed; preference differences on "
                f"{len(diff)} fixture(s) reported"
            ),
            fixtures=len(fixtures),
            diff=diff,
        )
    return ReplayOutcome(
        status="pass",
        detail=f"{len(fixtures)} fixtures replayed; decisions identical to the baseline",
        fixtures=len(fixtures),
    )
