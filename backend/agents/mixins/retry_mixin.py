"""Retry mixin for Agent resilience."""

import asyncio
from typing import Callable, Any


class RetryMixin:
    """Agent重试能力"""

    def execute_with_retry(
        self,
        action: Callable[[], Any],
        max_retries: int = 3,
        timeout: float = 30.0
    ) -> Any:
        """执行操作，失败时重试"""
        for attempt in range(max_retries):
            try:
                return action()
            except TimeoutError:
                if attempt == max_retries - 1:
                    raise
        return None

    async def execute_with_retry_async(
        self,
        action: Callable[[], Any],
        max_retries: int = 3,
        timeout: float = 30.0
    ) -> Any:
        """异步执行操作，失败时重试"""
        for attempt in range(max_retries):
            try:
                return await asyncio.wait_for(action(), timeout=timeout)
            except (TimeoutError, asyncio.TimeoutError):
                if attempt == max_retries - 1:
                    raise
        return None