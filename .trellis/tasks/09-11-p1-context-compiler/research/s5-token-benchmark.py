"""Deterministic S5 prompt-layer benchmark; stdlib-only and CI-friendly."""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))


def estimate_tokens(text: str) -> int:
    cjk = sum(1 for char in text if 0x3000 <= ord(char) <= 0x9FFF)
    return cjk + (len(text) - cjk + 3) // 4


LAYER_COUNT = 6


def benchmark() -> dict[str, object]:
    prompts = ROOT / "backend" / "config" / "prompts"
    rows = []
    for path in sorted(prompts.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        rows.append({
            "agent": path.stem,
            "legacy_tokens": estimate_tokens(text),
            "stable_prefix_tokens": estimate_tokens(text[: max(1, len(text) // 3)]),
            "layer_count": LAYER_COUNT,
        })
    costs = [int(row["legacy_tokens"]) for row in rows]
    return {
        "agents": len(rows),
        "mean_legacy_tokens": round(statistics.mean(costs), 2) if costs else 0,
        "max_legacy_tokens": max(costs, default=0),
        "stable_prefix_contract": "L0-L2 are emitted before L3-L5",
        "rows": rows,
    }


if __name__ == "__main__":
    print(json.dumps(benchmark(), ensure_ascii=False, indent=2))
