#!/usr/bin/env python3
"""Compare the previous and current lightweight-model routes.

This benchmark uses fixed, synthetic prompts and never starts a workflow. It
records wall-clock latency, provider token metadata, structural output quality,
and optional output samples so a human can review the content-quality delta.
Live provider calls are opt-in via ``--live`` because they may incur cost.

Example:
    python scripts/benchmarks/llm_route_benchmark.py --live --samples 3 \
        --include-output
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from backend.config.models import TaskType
from backend.models.router import ModelRouter

OLD_MODEL = "astron-code-latest"
NEW_MODEL = "deepseek-v4-flash"


def _messages(task: TaskType) -> list[Any]:
    if task is TaskType.POLISH:
        return [
            SystemMessage(
                content=(
                    "你是小红书内容润色助手。只输出 JSON，不要 Markdown。字段必须为 "
                    "title、body、changes。保留事实，不新增产品功效，不使用夸张承诺。"
                )
            ),
            HumanMessage(
                content=(
                    "请去除下面文案的 AI 套话，保留自然口语和信息密度。\n"
                    "标题：周末在家也能完成的轻量收纳方法\n"
                    "正文：首先，其次，最后，这是一份非常实用的收纳指南。通过简单的方法，"
                    "你可以轻松打造舒适空间，欢迎大家一起尝试。\n"
                    "场景：租房、小户型、预算有限。"
                )
            ),
        ]
    if task is TaskType.MOCK_GEN:
        return [
            SystemMessage(
                content=(
                    "你生成虚构的结构化博主候选，只输出 JSON，不要 Markdown。"
                    "候选必须使用 mock_ 用户 ID。"
                )
            ),
            HumanMessage(
                content=(
                    "生成 3 个“租房收纳”赛道的虚构博主候选。格式："
                    '{"candidates":[{"user_id":"mock_001","nickname":"...",'
                    '"follower_count":10000,"note_count":50,"total_engagement":2000,'
                    '"top_note_title":"..."}]}'
                )
            ),
        ]
    return [
        SystemMessage(
            content=("你生成虚构的爆款参考笔记，只输出 JSON，不要 Markdown，不要声称真实搜索。")
        ),
        HumanMessage(
            content=(
                "为“租房收纳”生成 3 条虚构参考笔记。格式："
                '{"viral_posts":[{"title":"...","likes":100,'
                '"collects":50,"comments":10,"reason":"..."}]}'
            )
        ),
    ]


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, default=str)


def _parse_json(content: str) -> dict[str, Any] | None:
    cleaned = content.strip()
    if "```" in cleaned:
        parts = cleaned.split("```")
        cleaned = parts[1].removeprefix("json").strip() if len(parts) > 1 else cleaned
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _quality_proxy(task: TaskType, content: str) -> dict[str, Any]:
    parsed = _parse_json(content)
    if task is TaskType.MOCK_GEN:
        key = "candidates"
    elif task is TaskType.VIRAL_MATCHING:
        key = "viral_posts"
    else:
        key = "changes"
    value = parsed.get(key) if parsed else None
    count = len(value) if isinstance(value, list) else None
    return {
        "valid_json": parsed is not None,
        "expected_key": key,
        "expected_list_count": count,
        "nonempty": bool(content.strip()),
        "output_chars": len(content),
    }


def _usage(response: Any) -> dict[str, int]:
    metadata = getattr(response, "usage_metadata", None) or {}
    return {
        "input_tokens": int(metadata.get("input_tokens", 0) or 0),
        "output_tokens": int(metadata.get("output_tokens", 0) or 0),
        "total_tokens": int(metadata.get("total_tokens", 0) or 0),
    }


async def _run_route(
    task: TaskType, model_id: str, samples: int, include_output: bool
) -> list[dict[str, Any]]:
    router = ModelRouter(routing_overrides={task.value: model_id})
    model = router.get_model(task)
    messages = _messages(task)
    results: list[dict[str, Any]] = []
    for index in range(1, samples + 1):
        started = time.perf_counter()
        try:
            response = await model.ainvoke(messages)
            content = _content_text(getattr(response, "content", ""))
            record: dict[str, Any] = {
                "sample": index,
                "ok": True,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "usage": _usage(response),
                "quality_proxy": _quality_proxy(task, content),
            }
            if include_output:
                record["output"] = content
            results.append(record)
        except Exception as error:  # benchmark must retain provider failures as evidence
            results.append(
                {
                    "sample": index,
                    "ok": False,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "error_type": type(error).__name__,
                }
            )
    return results


async def run(samples: int, include_output: bool) -> dict[str, Any]:
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "synthetic_input": True,
        "workflow_started": False,
        "samples_per_route": samples,
        "routes": {},
    }
    for task in (TaskType.POLISH, TaskType.MOCK_GEN, TaskType.VIRAL_MATCHING):
        report["routes"][task.value] = {
            "before": {
                "model": OLD_MODEL,
                "results": await _run_route(task, OLD_MODEL, samples, include_output),
            },
            "after": {
                "model": NEW_MODEL,
                "results": await _run_route(task, NEW_MODEL, samples, include_output),
            },
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="allow billable provider calls")
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--include-output", action="store_true")
    args = parser.parse_args()
    if not args.live:
        parser.error("refusing provider calls without --live")
    if args.samples < 1 or args.samples > 5:
        parser.error("--samples must be between 1 and 5")
    print(
        json.dumps(
            asyncio.run(run(args.samples, args.include_output)),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
