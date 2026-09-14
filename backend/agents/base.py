"""Base agent class — shared logic for all XHS Growth sub-agents."""

from __future__ import annotations

import contextvars
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    # BaseChatModel / BaseStore / XHSGrowthState are only used in annotations.
    # Importing them at module load drags in langchain_core.language_models →
    # langsmith.run_trees (~0.9s), langgraph.store.base, and state.schema →
    # langgraph.graph.message (~0.3s), on every import of backend.agents.base
    # — i.e. every agent/route import, including test collection. With
    # ``from __future__ import annotations`` they are strings, never evaluated
    # at runtime, so deferring to TYPE_CHECKING keeps the import chain light.
    from langchain_core.language_models import BaseChatModel
    from langgraph.store.base import BaseStore

    from backend.state.schema import XHSGrowthState

from backend.config.models import TaskType
from backend.models.router import get_model

logger = logging.getLogger("xhs_growth.agents")

# P0-W1 (task 09-11-p0-correctness-fixes): LLM perf entries live in a
# ContextVar, NOT on the agent instance. Agent classes are module-level
# singletons shared by every concurrent workflow on the single asyncio event
# loop; the old ``self._llm_perf_entries`` list leaked entries across tasks
# (cross-contaminated performance_log / cost attribution). Each asyncio task
# gets its own context, so set()/append inside execute() are invisible to
# sibling tasks — same isolation pattern as ``_tool_llm_cost`` in
# backend/agents/nodes/_base.py. Child tasks spawned by gather inside execute()
# inherit the context and mutate the SAME list object (append is visible;
# rebinding via set() is not — hence reset only at execute/__call__ scope).
_llm_perf_var: contextvars.ContextVar[list[dict[str, Any]] | None] = contextvars.ContextVar(
    "llm_perf_entries", default=None
)


class BaseAgent(ABC):
    """所有子 Agent 的基类"""

    task_type: TaskType = TaskType.ROUTING
    agent_name: str = "base"
    prompt_file: str = ""

    def __init__(self) -> None:
        self._model: BaseChatModel | None = None
        self._prompt_template: dict[str, str] | None = None

    # ── LLM perf entry capture (ContextVar-scoped, P0-W1) ──

    @staticmethod
    def _current_llm_perf_entries() -> list[dict[str, Any]]:
        """The live per-context llm perf entry list (created if absent)."""
        entries = _llm_perf_var.get()
        if entries is None:
            entries = []
            _llm_perf_var.set(entries)
        return entries

    @staticmethod
    def _drain_llm_perf() -> list[dict[str, Any]]:
        """Read (and detach) the accumulated llm perf entries for this context.

        Consumers that write telemetry use this instead of touching
        instance state — the returned list is owned by the caller afterwards.
        """
        entries = _llm_perf_var.get() or []
        _llm_perf_var.set([])
        return entries

    @property
    def model(self) -> BaseChatModel:
        if self._model is None:
            self._model = get_model(self.task_type.value)
        return self._model

    async def _llm_ainvoke(self, messages: list[Any]) -> Any:
        """Invoke the routed model and capture a kind:"llm" perf_log entry.

        Wraps :meth:`model.ainvoke` with timing + token/cost capture (via
        :func:`backend.agents.nodes._base.llm_perf_entry`). Entries accumulate
        on a per-asyncio-task ContextVar (P0-W1; formerly a shared instance
        list that cross-contaminated concurrent workflows); the node wrapper
        merges them with the node-level entry and emits the batch to the Event
        store. Reset per execute() via :meth:`_reset_llm_perf`. Best-effort: a
        capture failure never breaks the call.
        """
        from datetime import UTC, datetime

        from backend.agents.nodes._base import llm_perf_entry
        from backend.config.models import get_model_id_for_task

        started = datetime.now(UTC).isoformat()
        # ponytail: precise ainvoke wall-clock (perf_counter), separate from the
        # ISO started/completed pair used for cost-window filtering. The pair
        # above also covers entry-build overhead; ainvoke_ms isolates the call.
        import time

        _ainvoke_start = time.perf_counter()
        response = await self.model.ainvoke(messages)
        ainvoke_ms = (time.perf_counter() - _ainvoke_start) * 1000.0
        try:
            entry = llm_perf_entry(
                self.agent_name,
                response,
                get_model_id_for_task(self.task_type),  # routed model id
                started_at=started,
                completed_at=datetime.now(UTC).isoformat(),
            )
            if entry is not None:
                entry["ainvoke_ms"] = round(ainvoke_ms, 3)
                self._current_llm_perf_entries().append(entry)
        except Exception as exc:  # best-effort: never break the call
            logger.debug("llm perf entry capture failed: %s", exc)
        return response

    def _reset_llm_perf(self) -> None:
        """Start a fresh llm perf entry accumulation for this context.

        Called at the start of every agent execute(); signature unchanged so
        all 13 call sites keep working. The new list is bound to the current
        asyncio task's context (P0-W1), never to the shared agent instance.
        """
        _llm_perf_var.set([])

    @property
    def prompt_template(self) -> dict[str, str]:
        if self._prompt_template is None:
            self._prompt_template = self._load_prompt()
        return self._prompt_template

    def _load_prompt(self) -> dict[str, str]:
        if not self.prompt_file:
            return {"system": "", "user_template": ""}
        path = Path(__file__).parent.parent / "config" / "prompts" / self.prompt_file
        if path.exists():
            import yaml

            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return {
                "system": data.get("system", ""),
                "user_template": data.get("user_template", ""),
            }
        return {"system": "", "user_template": ""}

    def _build_system_prompt(self, state: XHSGrowthState, extra_context: str = "") -> str:
        """Deprecated legacy template path — P1b-S4-7 removed all callers.

        Kept as a hard-fail stub so any future (re)introduction of the
        per-agent ``template.replace`` path fails loudly instead of silently
        bypassing the Context Compiler pipeline. Agents compile via
        ``ContextCompiler.compile_prompt`` (consumer-map 收口).
        """
        raise NotImplementedError(
            "BaseAgent._build_system_prompt was removed in P1b-S4-7: "
            "agents must assemble prompts via ContextCompiler.compile_prompt"
        )

    async def _recall_memory(
        self,
        store: BaseStore,
        account_id: str,
        query: str,
        namespace: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Deprecated legacy recall path — P1b-S4-7 removed all callers.

        Kept as a hard-fail stub (same rationale as ``_build_system_prompt``):
        recall must go through ``backend.context.retrieval.recall_namespaces``
        so every outcome carries the D6' degradation signal.
        """
        raise NotImplementedError(
            "BaseAgent._recall_memory was removed in P1b-S4-7: "
            "recall must go through backend.context.retrieval.recall_namespaces"
        )

    def _parse_json_response(self, content: str) -> dict[str, Any]:
        """从 LLM 响应中提取 JSON（增强版，处理多种格式和常见语法错误）"""
        import time

        # ponytail: record parse wall-clock onto the most recent llm perf entry.
        # Parse (regex repair + bracket fix + json.loads) can dominate when the
        # model returns malformed JSON needing heavy repair. Best-effort: if no
        # entry exists yet, the timing is simply discarded.
        _parse_start = time.perf_counter()
        try:
            return self._parse_json_response_impl(content)
        finally:
            try:
                entries = _llm_perf_var.get()
                if entries:
                    entries[-1]["parse_ms"] = round(
                        (time.perf_counter() - _parse_start) * 1000.0, 3
                    )
            except Exception:
                pass

    def _parse_json_response_impl(self, content: str) -> dict[str, Any]:
        """从 LLM 响应中提取 JSON（增强版，处理多种格式和常见语法错误）"""
        import re

        def repair_json(json_str: str) -> str:
            """修复常见的 JSON 语法错误"""
            # 修复缺少引号的值（如 #hashtag -> "#hashtag"）
            # 匹配数组中缺少引号的元素: [, #value, -> , "#value",
            json_str = re.sub(r',\s*#([^\s,\[\]"]+)', r', "#\1"', json_str)
            # 修复缺少引号的值开头: [#value, -> ["#value",
            json_str = re.sub(r'\[\s*#([^\s,\[\]"]+)', r'["#\1"', json_str)
            # 修复缺少引号的值结尾: , #value] -> , "#value"]
            json_str = re.sub(r',\s*#([^\s,\[\]"]+)\s*\]', r', "#\1"]', json_str)

            # 修复括号不匹配：] 闭合 { 或 } 闭合 [
            result = []
            stack = []
            for ch in json_str:
                if ch in ("{", "["):
                    stack.append(ch)
                    result.append(ch)
                elif ch == "}" and stack and stack[-1] == "[":
                    stack.pop()
                    result.append("]")
                elif ch == "]" and stack and stack[-1] == "{":
                    stack.pop()
                    result.append("}")
                elif ch in ("}", "]"):
                    if stack:
                        stack.pop()
                    result.append(ch)
                else:
                    result.append(ch)
            json_str = "".join(result)
            return json_str

        def extract_json_from_markdown(text: str) -> str:
            """从 markdown 代码块中提取 JSON"""
            if "```json" in text:
                return text.split("```json")[1].split("```")[0].strip()
            if "```" in text:
                parts = text.split("```")
                for i, part in enumerate(parts):
                    if i % 2 == 1:  # 奇数索引是代码块内容
                        return part.strip()
            return text

        try:
            # 1. 提取 JSON 内容
            json_content = extract_json_from_markdown(content)

            # 2. 尝试直接解析
            try:
                return cast(dict[str, Any], json.loads(json_content))
            except json.JSONDecodeError:
                pass

            # 3. 尝试修复常见语法错误后解析
            repaired = repair_json(json_content)
            try:
                return cast(dict[str, Any], json.loads(repaired))
            except json.JSONDecodeError:
                pass

            # 4. 尝试从文本中找到 JSON 对象边界
            start = json_content.find("{")
            end = json_content.rfind("}")
            if start != -1 and end != -1 and end > start:
                json_str = json_content[start : end + 1]
                try:
                    return cast(dict[str, Any], json.loads(json_str))
                except json.JSONDecodeError:
                    repaired = repair_json(json_str)
                    try:
                        return cast(dict[str, Any], json.loads(repaired))
                    except json.JSONDecodeError:
                        pass

            # 5. 尝试正则匹配 JSON 对象
            json_pattern = r"\{(?:[^{}]|(?:\{(?:[^{}]|(?:\{[^{}]*\}))*\}))*\}"
            matches = re.findall(json_pattern, content)
            for match in matches:
                try:
                    return cast(dict[str, Any], json.loads(match))
                except json.JSONDecodeError:
                    repaired = repair_json(match)
                    try:
                        return cast(dict[str, Any], json.loads(repaired))
                    except json.JSONDecodeError:
                        continue

            # 所有方法都失败
            logger.warning(f"Failed to parse JSON response from {self.agent_name}: {content[:200]}")
            return {"raw_content": content}
        except (json.JSONDecodeError, IndexError) as e:
            logger.warning(f"JSON decode error in {self.agent_name}: {e}")
            return {"raw_content": content}

    @abstractmethod
    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        """执行 Agent 核心逻辑，返回状态更新字典"""
        ...

    async def __call__(self, state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
        """LangGraph node entry point.

        Wraps execute() with node-level timing → appends one performance-log
        entry per call. On success, the entries are written to the Event store
        (P1a-S2: telemetry no longer rides the checkpoint, which used to
        re-serialize it on every superstep). Recording is best-effort: a timer
        or storage failure must not break the node (see PRD: 节点级指标).

        On failure we return an error state update (NOT raise) so LangGraph
        merges it and should_plan/orchestrator routers can read retry_count
        to decide stateful retry vs termination. This activates the original
        stateful retry design — see prd ADR-lite (07-07-remove-handle-agent-error-dead-code).
        LangGraph's RetryPolicy (framework-level) only triggers on exceptions;
        by not raising we trade it for stateful cross-super-step retry.
        """
        from backend.agents.nodes._base import _tool_llm_cost, node_perf_entry
        from backend.core.error_handling import handle_agent_error

        started = _now_iso()
        retries = int(state.get("retry_count", 0) or 0)
        # P0-W1: open a per-execute llm-perf context scope (token reset in the
        # finally below) so entries never survive this call. Set a per-execute
        # tool-LLM-cost accumulator so enrich_with_llm calls made inside tools
        # during execute() can append kind:"llm" entries. Drained + reset below
        # (both paths) so tool-path token cost reaches the Event store and the
        # /analytics/costs reader; the set/reset token isolates per-execute and
        # prevents stale leakage across requests.
        perf_token = _llm_perf_var.set([])
        tool_token = _tool_llm_cost.set([])
        try:
            try:
                result = await self.execute(state, store)
            except Exception as e:
                logger.error(f"Agent {self.agent_name} failed: {e}", exc_info=True)
                # Drain tool-path cost captured during execute() BEFORE building
                # the failed entry so it rides the perf log; reset via token.
                perf_entries = self._drain_llm_perf()
                perf_entries.extend(_tool_llm_cost.get() or [])
                # Stateful retry: return error state (not raise) so LangGraph
                # merges it and should_plan/orchestrator routers can read
                # retry_count to retry/terminate. See prd ADR-lite.
                result = handle_agent_error(e, state, agent_name=self.agent_name)
                # Best-effort failed perf entry — now possible because we return
                # (not raise), so the dict reaches the reducer.
                try:
                    entries = [
                        node_perf_entry(
                            self.agent_name,
                            started_at=started,
                            completed_at=_now_iso(),
                            status="failed",
                            error=str(e),
                            retries=retries + 1,
                        )
                    ]
                    entries.extend(perf_entries)
                    await _emit_perf_entries(state, entries)
                except Exception as timer_err:  # best-effort: never break the node
                    logger.debug("perf event emit failed: %s", timer_err)
                return result

            # Drain tool-path cost captured during execute() BEFORE building the
            # success entry so it rides the perf log; reset via token below.
            perf_entries = self._drain_llm_perf()
            perf_entries.extend(_tool_llm_cost.get() or [])
            result["current_agent"] = self.agent_name
            result["error"] = None  # Clear stale error on success
            try:
                # Merge node-level entry with any kind:"llm" entries captured by
                # _llm_ainvoke() during execute() (token/cost per LLM call).
                entries = [
                    node_perf_entry(
                        self.agent_name,
                        started_at=started,
                        completed_at=_now_iso(),
                        status="success",
                        error=None,
                        retries=retries,
                    )
                ]
                entries.extend(perf_entries)
                await _emit_perf_entries(state, entries)
            except Exception as timer_err:  # best-effort: never break the node
                logger.debug("perf event emit failed: %s", timer_err)
            return result
        finally:
            # Always reset via the tokens so a nested/errored execute never
            # leaks stale entries to the next request (drain already happened
            # above).
            _tool_llm_cost.reset(tool_token)
            _llm_perf_var.reset(perf_token)


async def _emit_perf_entries(state: Any, entries: list[dict[str, Any]]) -> None:
    """Write node/llm perf entries to the Event store (P1a-S2).

    Telemetry used to ride the returned state dict under ``performance_log`` so
    the ``_append_list`` reducer could merge it into the checkpoint. The Event
    store replaces that: nodes keep their state updates free of telemetry.
    """
    from backend.state.events import emit_events, resolve_thread_id

    await emit_events(resolve_thread_id(state), entries)


def _now_iso() -> str:
    """UTC ISO8601 timestamp for performance-log entries."""
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
