"""P3/E2 wiring: one injected policy reaches the production call sites.

The contract has two halves and every test below is one of them: the **default**
policy must leave today's behaviour byte-identical, and a **non-default** policy
must actually change the router, the context compiler and the tool gateway.
Everything stays offline — no network, no real provider SDK, no real tool; the
tool registry capabilities are local fakes, which is also the regression guard
against the gateway consulting the production catalogue on the default path.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from backend.config.models import ModelProvider, TaskType
from backend.context.compiler import ContextCompiler
from backend.context.models import (
    ContextItem,
    PromptLayer,
    RetrievalMode,
    RetrievalResult,
    RunContext,
)
from backend.harness.policy import DefaultHarnessPolicy, ToolLimits, default_policy, describe
from backend.harness.runtime import (
    ENV_POLICY_VAR,
    HarnessPolicyLoadError,
    configure_policy,
    get_policy,
    is_default_policy,
    load_policy,
    policy_generation,
    reset_policy,
)
from backend.models import router as router_module
from backend.models.router import ModelRouter
from backend.tools.runtime import (
    ErrorKind,
    LatencyClass,
    RetryPolicy,
    SideEffect,
    ToolGateway,
    ToolRegistry,
    ToolSpec,
)
from tests.unit.harness._fake_policies import ENV_POLICY_INSTANCE, EnvVariantPolicy, env_policy

# ── fakes ──────────────────────────────────────────────────────────────────


class EscalatingPolicy(DefaultHarnessPolicy):
    """A variant that adds escalation targets; everything else stays default."""

    def __init__(self, targets: tuple[str, ...]) -> None:
        self._targets = targets

    def escalation_targets(self, task_type: TaskType) -> tuple[str, ...]:
        return self._targets


class RoutingPolicy(DefaultHarnessPolicy):
    """A variant that always routes to one model id."""

    def __init__(self, model_id: str) -> None:
        self._model_id = model_id

    def route_model(self, task_type: TaskType) -> str:
        return self._model_id


class PhaseBudgetPolicy(DefaultHarnessPolicy):
    """A variant whose context budget only applies to one workflow phase."""

    def __init__(self, *, phase: str = "publishing", budget: int | None = 18) -> None:
        self._phase = phase
        self._budget = budget

    def context_budget(self, *, phase: str = "") -> int | None:
        return self._budget if phase == self._phase else None


class CatalogOnlyPolicy(DefaultHarnessPolicy):
    """Changes only the budget: its ``tool_limits`` still hits the catalogue."""

    def context_budget(self, *, phase: str = "") -> int | None:
        return 1


class ToolLimitPolicy(DefaultHarnessPolicy):
    """A variant that declares tool limits without consulting the catalogue."""

    def __init__(self, *, max_concurrency: int | None = None, timeout_s: float | None = None):
        self._max_concurrency = max_concurrency
        self._timeout_s = timeout_s

    def tool_limits(self, capability: str) -> ToolLimits:
        return ToolLimits(
            capability=capability,
            max_concurrency=self._max_concurrency,
            timeout_s=self._timeout_s,
        )


# ── fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolated_policy(monkeypatch: pytest.MonkeyPatch) -> Any:
    """No test may inherit (or leak) an explicit policy or a policy env var."""
    monkeypatch.delenv(ENV_POLICY_VAR, raising=False)
    reset_policy()
    yield
    reset_policy()


@pytest.fixture(autouse=True)
def _offline_account_gate(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Deterministic degraded mode: the distributed slot gate never engages."""
    monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: False)
    from backend.tools.runtime.account_gate import reset_account_gates_for_tests

    reset_account_gates_for_tests()
    yield
    reset_account_gates_for_tests()


# ── backend.harness.runtime: resolution, loading, generation ───────────────


def test_default_policy_matches_todays_behaviour() -> None:
    policy = get_policy()
    assert is_default_policy(policy)
    # Not identity: the default is stateless, so an equal snapshot is the claim.
    assert describe(policy) == describe(default_policy())


def test_env_spec_is_read_lazily_and_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    assert is_default_policy(get_policy())  # first read with no env configured
    monkeypatch.setenv(ENV_POLICY_VAR, "tests.unit.harness._fake_policies:env_policy")
    reset_policy()  # forget the "no env" answer
    policy = get_policy()
    assert isinstance(policy, EnvVariantPolicy)
    assert not is_default_policy(policy)
    assert get_policy() is policy  # the import result is cached, not re-imported


def test_env_spec_may_name_a_module_level_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        ENV_POLICY_VAR,
        "tests.unit.harness._fake_policies:ENV_POLICY_INSTANCE",
    )
    reset_policy()
    assert get_policy() is ENV_POLICY_INSTANCE


@pytest.mark.parametrize(
    "spec",
    [
        "no_such_module_xyz:factory",
        "backend.harness.policy:missing_attribute",
        "backend.harness.policy:describe",  # callable, but returns a dict
        "backend.harness.policy",  # no ":factory"
        "backend.harness.policy:",  # empty factory
    ],
)
def test_invalid_env_spec_raises_and_is_not_cached(
    monkeypatch: pytest.MonkeyPatch, spec: str
) -> None:
    monkeypatch.setenv(ENV_POLICY_VAR, spec)
    reset_policy()
    with pytest.raises(HarnessPolicyLoadError) as caught:
        get_policy()
    assert isinstance(caught.value, ValueError)
    assert isinstance(caught.value, RuntimeError)
    assert spec in str(caught.value)
    # A broken deployment spec keeps failing; it must not quietly become default.
    with pytest.raises(HarnessPolicyLoadError):
        get_policy()


def test_load_policy_calls_the_factory() -> None:
    policy = load_policy("backend.harness.policy:default_policy")
    assert isinstance(policy, DefaultHarnessPolicy)
    assert load_policy("tests.unit.harness._fake_policies:env_policy").context_budget() is None


def test_configure_wins_over_env_and_reset_restores_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_POLICY_VAR, "tests.unit.harness._fake_policies:env_policy")
    reset_policy()
    injected = EscalatingPolicy(("magpie-pdf-ocr",))
    configure_policy(injected)
    assert get_policy() is injected

    reset_policy()
    assert isinstance(get_policy(), EnvVariantPolicy)  # env is the fallback again


def test_configure_and_reset_bump_the_generation() -> None:
    generation = policy_generation()
    configure_policy(EnvVariantPolicy())
    assert policy_generation() == generation + 1
    reset_policy()
    assert policy_generation() == generation + 2
    assert is_default_policy(get_policy())
    # Resolution itself is not a policy change.
    get_policy()
    assert policy_generation() == generation + 2


def test_is_default_policy_is_an_exact_type_check() -> None:
    class SubclassedDefault(DefaultHarnessPolicy):
        pass

    assert is_default_policy(default_policy()) is True
    assert is_default_policy(SubclassedDefault()) is False
    assert is_default_policy(env_policy()) is False


# ── backend.models.router: candidate chain, routing, cache invalidation ────


class _FakeChat:
    """Duck-typed chat model: the wrappers only need invoke/ainvoke."""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    async def ainvoke(self, *args: Any, **kwargs: Any) -> str:
        return self.model_id

    def invoke(self, *args: Any, **kwargs: Any) -> str:
        return self.model_id


class _FakeConfig:
    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self.model_name = model_id


def _patch_model_construction(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Offline router: records every model *construction*, real registry ids."""
    constructed: list[str] = []

    def fake_get_model_config(model_id: str) -> _FakeConfig:
        return _FakeConfig(model_id)

    def fake_create_model(config: Any, timeout: int | None = None) -> _FakeChat:
        constructed.append(config.model_id)
        return _FakeChat(config.model_id)

    monkeypatch.setattr("backend.config.models.get_model_config", fake_get_model_config)
    monkeypatch.setattr(router_module, "_create_model", fake_create_model)
    return constructed


def test_default_candidate_chain_is_todays_single_model() -> None:
    assert ModelRouter()._candidate_model_ids(TaskType.WRITING) == ["magpie-deepseek-v4.1-flash"]


def test_router_overrides_keep_todays_fallback_chain() -> None:
    router = ModelRouter({"writing": "mimo-v2.6-flash"})
    assert router._candidate_model_ids(TaskType.WRITING) == [
        "mimo-v2.6-flash",
        "magpie-deepseek-v4.1-flash",
    ]


def test_policy_escalation_extends_the_chain_without_duplicates() -> None:
    configure_policy(EscalatingPolicy(("magpie-pdf-ocr", "magpie-deepseek-v4.1-flash")))
    assert ModelRouter()._candidate_model_ids(TaskType.WRITING) == [
        "magpie-deepseek-v4.1-flash",
        "magpie-pdf-ocr",
    ]


def test_get_model_honours_policy_route_model(monkeypatch: pytest.MonkeyPatch) -> None:
    constructed = _patch_model_construction(monkeypatch)
    configure_policy(RoutingPolicy("magpie-pdf-ocr"))
    model = ModelRouter().get_model(TaskType.WRITING)
    assert constructed == ["magpie-pdf-ocr"]
    assert model.model_id == "magpie-pdf-ocr"


def test_router_override_still_beats_policy_route_model(monkeypatch: pytest.MonkeyPatch) -> None:
    constructed = _patch_model_construction(monkeypatch)
    configure_policy(RoutingPolicy("magpie-pdf-ocr"))
    ModelRouter({"writing": "gpt-4o"}).get_model(TaskType.WRITING)
    assert constructed == ["gpt-4o"]


def test_default_fallback_is_still_lazy(monkeypatch: pytest.MonkeyPatch) -> None:
    constructed = _patch_model_construction(monkeypatch)
    model = ModelRouter({"writing": "mimo-v2.6-flash"}).get_model(TaskType.WRITING)
    assert constructed == ["mimo-v2.6-flash"]  # fallback not built yet
    fallback = model._fallback_factory()  # today's lazy creation point
    assert constructed == ["mimo-v2.6-flash", "magpie-deepseek-v4.1-flash"]
    assert fallback.model_id == "magpie-deepseek-v4.1-flash"


def test_escalation_chain_is_nested_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    constructed = _patch_model_construction(monkeypatch)
    configure_policy(EscalatingPolicy(("magpie-pdf-ocr", "gpt-4o")))
    model = ModelRouter().get_model(TaskType.WRITING)
    assert constructed == ["magpie-deepseek-v4.1-flash"]
    level_one = model._fallback_factory()
    assert constructed == ["magpie-deepseek-v4.1-flash", "magpie-pdf-ocr"]
    level_two = level_one._fallback_factory()
    assert constructed == [
        "magpie-deepseek-v4.1-flash",
        "magpie-pdf-ocr",
        "gpt-4o",
    ]
    assert level_two.model_id == "gpt-4o"


def test_unknown_escalation_id_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        router_module,
        "_create_model",
        lambda config, timeout=None: _FakeChat(getattr(config, "model_id", "x")),
    )
    configure_policy(EscalatingPolicy(("no-such-model",)))
    with pytest.raises(KeyError):
        ModelRouter().get_model(TaskType.WRITING)


def test_model_cache_is_invalidated_by_policy_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed = _patch_model_construction(monkeypatch)
    router = ModelRouter()
    first = router.get_model(TaskType.WRITING)
    assert router.get_model(TaskType.WRITING) is first  # cache hit
    assert constructed == ["magpie-deepseek-v4.1-flash"]

    configure_policy(RoutingPolicy("magpie-pdf-ocr"))
    second = router.get_model(TaskType.WRITING)
    assert second is not first
    assert constructed == ["magpie-deepseek-v4.1-flash", "magpie-pdf-ocr"]
    assert second.model_id == "magpie-pdf-ocr"


def test_providers_in_use_includes_escalation_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_policy(EscalatingPolicy(("claude-sonnet-4-20250514",)))
    assert ModelProvider.ANTHROPIC in router_module._providers_in_use()


# ── backend.context.compiler: phase budget ─────────────────────────────────


def _run_context(phase: str = "") -> RunContext:
    return RunContext(thread_id="t", account_id="acc", niche="母婴", phase=phase)


def _budget_retrievals() -> tuple[RetrievalResult, ...]:
    long_l5 = ContextItem(body="五" * 40, source="tool:xhs", priority=0)
    short_l5 = ContextItem(body="五" * 5, source="tool:xhs", priority=9)
    l4 = ContextItem(body="四" * 5, source="memory:performance_insights", priority=1)
    return (
        RetrievalResult(
            namespace="workflow",
            layer=PromptLayer.L5_OBSERVATION,
            items=(long_l5, short_l5),
            mode=RetrievalMode.HIT,
        ),
        RetrievalResult(
            namespace="performance_insights",
            layer=PromptLayer.L4_MEMORY,
            items=(l4,),
            mode=RetrievalMode.HIT,
        ),
    )


def _compile(**context_kwargs: Any) -> Any:
    return ContextCompiler().compile_prompt(
        _run_context(**context_kwargs),
        "零" * 10,  # L0 system section: 10 reserved tokens
        retrievals=_budget_retrievals(),
    )


def test_policy_context_budget_is_applied_for_the_run_phase() -> None:
    configure_policy(PhaseBudgetPolicy(phase="publishing", budget=18))
    prompt = _compile(phase="publishing")
    # Same arithmetic as the explicit-budget compiler test: L0 reserves 10,
    # the allowance is 8, so L5 drops both items and L4 survives whole.
    assert PromptLayer.L5_OBSERVATION not in prompt.layers
    assert prompt.layers[PromptLayer.L4_MEMORY] == "四" * 5
    assert prompt.layers[PromptLayer.L0_SYSTEM] == "零" * 10
    assert prompt.total_token_cost <= 18


def test_policy_context_budget_is_ignored_for_another_phase() -> None:
    configure_policy(PhaseBudgetPolicy(phase="publishing", budget=18))
    prompt = _compile(phase="")
    assert "五" * 40 in prompt.layers[PromptLayer.L5_OBSERVATION]


def test_default_policy_still_does_not_trim() -> None:
    prompt = _compile(phase="publishing")
    assert "五" * 40 in prompt.layers[PromptLayer.L5_OBSERVATION]
    assert PromptLayer.L4_MEMORY in prompt.layers


def test_explicit_budget_beats_the_policy() -> None:
    configure_policy(PhaseBudgetPolicy(phase="publishing", budget=18))
    prompt = ContextCompiler().compile_prompt(
        _run_context(phase="publishing"),
        "零" * 10,
        retrievals=_budget_retrievals(),
        budget=1000,
    )
    assert "五" * 40 in prompt.layers[PromptLayer.L5_OBSERVATION]


# ── backend.tools.runtime.gateway: effective tool limits ───────────────────


def _tool_spec(
    *,
    timeout_s: float | None = 1.0,
    max_concurrency: int | None = None,
) -> ToolSpec:
    return ToolSpec(
        capability="demo.echo",
        summary="test double",
        side_effect=SideEffect.PURE,
        latency=LatencyClass.FAST,
        retry_policy=RetryPolicy(),
        timeout_s=timeout_s,
        max_concurrency=max_concurrency,
    )


def _gateway(fn: Any, *, timeout_s: float | None = 1.0, max_concurrency: int | None = None):
    registry = ToolRegistry()
    registry.register(_tool_spec(timeout_s=timeout_s, max_concurrency=max_concurrency), fn)
    return ToolGateway(registry, sleeper=_noop_sleep)


async def _noop_sleep(seconds: float) -> None:
    return None


async def _slow_tool(payload: Mapping[str, Any]) -> str:
    await asyncio.sleep(0.2)
    return "late"


async def _quick_tool(payload: Mapping[str, Any]) -> str:
    return "ok"


async def test_default_policy_uses_the_spec_declaration() -> None:
    """A custom-registry capability is not in the production catalogue.

    The default policy must therefore trust the spec — a catalogue lookup here
    would raise ``UnknownCapabilityError`` and break every fake capability.
    """
    result = await _gateway(_slow_tool, timeout_s=0.01).invoke("demo.echo", {})
    assert result.ok is False
    assert result.error_kind is ErrorKind.TIMEOUT
    assert "timeout after 0.01s" in result.error


async def test_default_policy_keeps_spec_max_concurrency() -> None:
    peak = 0
    active = 0

    async def tracked(payload: Mapping[str, Any]) -> str:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return "ok"

    gateway = _gateway(tracked, timeout_s=1.0, max_concurrency=1)
    results = await asyncio.gather(*(gateway.invoke("demo.echo", {}) for _ in range(3)))
    assert all(result.ok for result in results)
    assert peak == 1


async def test_policy_timeout_wins_over_the_spec() -> None:
    configure_policy(ToolLimitPolicy(timeout_s=0.01))
    # The spec's own timeout (1.0s) is wide enough for the 0.2s tool; only the
    # policy's 0.01s can make this a timeout.
    result = await _gateway(_slow_tool, timeout_s=1.0).invoke("demo.echo", {})
    assert result.error_kind is ErrorKind.TIMEOUT
    assert "timeout after 0.01s" in result.error


async def test_policy_none_timeout_removes_the_timeout() -> None:
    configure_policy(ToolLimitPolicy(timeout_s=None))
    result = await _gateway(_slow_tool, timeout_s=0.01).invoke("demo.echo", {})
    assert result.ok is True
    assert result.value == "late"


async def test_policy_max_concurrency_is_enforced() -> None:
    peak = 0
    active = 0

    async def tracked(payload: Mapping[str, Any]) -> str:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return "ok"

    configure_policy(ToolLimitPolicy(max_concurrency=1, timeout_s=1.0))
    gateway = _gateway(tracked, timeout_s=1.0, max_concurrency=None)
    results = await asyncio.gather(*(gateway.invoke("demo.echo", {}) for _ in range(3)))
    assert all(result.ok for result in results)
    assert peak == 1


async def test_policy_limits_for_unknown_capabilities_fall_back_to_the_spec() -> None:
    configure_policy(CatalogOnlyPolicy())  # inherits the catalogue-backed tool_limits
    result = await _gateway(_slow_tool, timeout_s=0.01).invoke("demo.echo", {})
    assert result.error_kind is ErrorKind.TIMEOUT
    assert "timeout after 0.01s" in result.error


@pytest.mark.parametrize(
    ("max_concurrency", "timeout_s"),
    [(0, 1.0), (-2, 1.0), (None, 0.0), (None, -0.5)],
)
async def test_invalid_policy_limits_raise_value_error(
    max_concurrency: int | None, timeout_s: float | None
) -> None:
    configure_policy(ToolLimitPolicy(max_concurrency=max_concurrency, timeout_s=timeout_s))
    gateway = _gateway(_quick_tool)
    with pytest.raises(ValueError, match="demo.echo"):
        await gateway.invoke("demo.echo", {})
