"""Token usage tracking and budget enforcement."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("xhs_growth.cost_tracker")


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    task: str = ""
    timestamp: str = ""


# 每 1K token 大致成本 (USD)
COST_PER_1K: dict[str, dict[str, float]] = {
    "claude-sonnet-4-20250514": {"input": 0.003, "output": 0.015},
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "deepseek-chat": {"input": 0.00014, "output": 0.00028},
    "qwen-plus": {"input": 0.0004, "output": 0.0012},
}


class CostTracker:
    """追踪 LLM 调用成本，日预算熔断"""

    def __init__(self, daily_budget_usd: float = 10.0):
        self.daily_budget = daily_budget_usd
        self._usage: list[TokenUsage] = []
        self._circuit_open = False

    def record(self, model: str, task: str, input_tokens: int, output_tokens: int) -> None:
        costs = COST_PER_1K.get(model, {"input": 0.001, "output": 0.005})
        cost = (input_tokens / 1000) * costs["input"] + (output_tokens / 1000) * costs["output"]

        usage = TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            model=model,
            task=task,
            timestamp=datetime.now(UTC).isoformat(),
        )
        self._usage.append(usage)
        logger.info(f"Cost: ${cost:.4f} | Model: {model} | Task: {task}")

        if self.today_total() > self.daily_budget:
            self._circuit_open = True
            logger.warning(
                f"Daily budget exceeded: ${self.today_total():.2f} > ${self.daily_budget:.2f}"
            )

    @property
    def circuit_open(self) -> bool:
        return self._circuit_open

    def today_total(self) -> float:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        return sum(u.cost_usd for u in self._usage if u.timestamp.startswith(today))

    def summary(self) -> dict[str, Any]:
        return {
            "total_cost_usd": sum(u.cost_usd for u in self._usage),
            "today_cost_usd": self.today_total(),
            "total_calls": len(self._usage),
            "circuit_open": self._circuit_open,
            "by_model": self._by_model(),
        }

    def _by_model(self) -> dict[str, float]:
        result: dict[str, float] = {}
        for u in self._usage:
            result[u.model] = result.get(u.model, 0.0) + u.cost_usd
        return result
