"""LLM Enrichment Service - Shared service for tool LLM enhancement.

Provides a unified layer for tools to use LLM with graceful fallback,
ensuring tools never fail completely and always return valid output.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

from langchain_core.messages import HumanMessage, SystemMessage

from backend.config.models import TaskType
from backend.models.context_cap import cap_context
from backend.models.router import get_model

logger = logging.getLogger("xhs_growth.llm_enrichment")


class LLMEnrichmentError(Exception):
    """Error during LLM enrichment."""

    pass


class LLMEnrichmentService:
    """Shared service for LLM-based data enrichment with graceful fallback.

    Usage:
        service = LLMEnrichmentService()
        result = await service.enrich_with_llm(
            task_type=TaskType.WRITING,
            prompt_template={"system": "...", "user_template": "..."},
            input_data={"keyword": "美食"},
            fallback_fn=lambda data: _algorithmic_analysis(data),
        )
    """

    def __init__(self) -> None:
        self._models: dict[str, Any] = {}

    def _get_model(self, task_type: TaskType) -> Any:
        """Get cached model for task type."""
        key = task_type.value
        if key not in self._models:
            self._models[key] = get_model(key)
        return self._models[key]

    def _parse_json_response(self, content: str) -> dict[str, Any] | list[Any]:
        """Extract JSON from LLM response content.

        Handles both raw JSON and markdown-wrapped JSON blocks.
        """
        # Try direct JSON parse first
        try:
            return cast(dict[str, Any] | list[Any], json.loads(content))
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown code blocks
        json_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
        matches = re.findall(json_pattern, content)
        if matches:
            for match in matches:
                try:
                    return cast(dict[str, Any] | list[Any], json.loads(match.strip()))
                except json.JSONDecodeError:
                    continue

        # Try finding JSON-like content in the response
        json_like_pattern = r"\{[\s\S]*\}|\[[\s\S]*\]"
        matches = re.findall(json_like_pattern, content)
        if matches:
            for match in matches:
                try:
                    return cast(dict[str, Any] | list[Any], json.loads(match))
                except json.JSONDecodeError:
                    continue

        raise LLMEnrichmentError(f"Could not parse JSON from response: {content[:100]}")

    async def enrich_with_llm(
        self,
        task_type: TaskType,
        prompt_template: dict[str, Any],
        input_data: dict[str, Any],
        fallback_fn: Callable[[dict[str, Any]], dict[str, Any] | list[Any]] | None = None,
    ) -> dict[str, Any] | list[Any]:
        """Enrich data with LLM, with automatic fallback.

        Args:
            task_type: Task type for model routing (WRITING, VISUAL, STRATEGY, etc.)
            prompt_template: Dict with "system" and "user_template" keys
            input_data: Dict of values to fill into user_template
            fallback_fn: Optional fallback function if LLM fails

        Returns:
            Enriched data dict/list, or fallback result
        """
        try:
            model = self._get_model(task_type)

            # Build prompts
            system_content = prompt_template.get("system", "")
            user_template = prompt_template.get("user_template", "")

            # Format user prompt with input data
            user_content = user_template.format(**input_data) if user_template else ""

            # Invoke LLM
            logger.debug(f"Invoking LLM for {task_type.value} enrichment")
            messages = cap_context(
                [
                    SystemMessage(content=system_content),
                    HumanMessage(content=user_content),
                ]
            )
            started_at = datetime.now(UTC).isoformat()
            response = await model.ainvoke(messages)

            # Capture token cost for the cost dashboard. Only accumulates when a
            # BaseAgent.__call__ scope set the ContextVar (workflow path); omp/
            # manual standalone callers leave it unset (None) and we skip. The
            # whole method is already in a try/except, but capture is itself
            # best-effort so a bug here never trips the fallback path.
            try:
                from backend.agents.nodes._base import _tool_llm_cost, llm_perf_entry
                from backend.config.models import get_model_id_for_task

                bucket = _tool_llm_cost.get()
                if bucket is not None:
                    completed = datetime.now(UTC).isoformat()
                    entry = llm_perf_entry(
                        f"tool:{task_type.value}",
                        response,
                        get_model_id_for_task(task_type),
                        started_at=started_at,
                        completed_at=completed,
                    )
                    if entry is not None:
                        bucket.append(entry)
            except Exception as exc:  # best-effort: never break the call
                logger.debug("tool llm cost capture failed for %s: %s", task_type.value, exc)

            # Parse response
            result = self._parse_json_response(response.content)
            logger.info(f"LLM enrichment succeeded for {task_type.value}")
            return result

        except Exception as e:
            logger.warning(f"LLM enrichment failed for {task_type.value}: {e}")

            # Use fallback if provided
            if fallback_fn:
                logger.info(f"Using fallback for {task_type.value}")
                return fallback_fn(input_data)

            # Return empty structure matching expected output type
            return {}

    async def generate_with_llm(
        self,
        task_type: TaskType,
        prompt_template: dict[str, Any],
        input_data: dict[str, Any],
        fallback_fn: Callable[[dict[str, Any]], list[Any]] | None = None,
    ) -> list[Any]:
        """Generate list output with LLM (for title_generator, etc).

        Same as enrich_with_llm but expects list output.
        """
        result = await self.enrich_with_llm(
            task_type=task_type,
            prompt_template=prompt_template,
            input_data=input_data,
            fallback_fn=fallback_fn,
        )

        # Ensure we return a list
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "items" in result:
            return cast(list[Any], result["items"])
        if isinstance(result, dict):
            # Single item, wrap in list
            return [result]

        return []


# Singleton instance
_service: LLMEnrichmentService | None = None


def get_llm_service() -> LLMEnrichmentService:
    """Get the global LLM enrichment service."""
    global _service
    if _service is None:
        _service = LLMEnrichmentService()
    return _service


__all__ = ["LLMEnrichmentService", "LLMEnrichmentError", "get_llm_service"]
