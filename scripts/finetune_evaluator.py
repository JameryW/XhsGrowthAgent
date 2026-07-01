#!/usr/bin/env python3
"""Finetune the RQGM evaluator judge model via LoRA/PEFT SFT.

Collects training samples from `evaluator_samples` (evaluator judgments +
back-filled engagement weak labels + human-review strong labels), exports
them to jsonl, and runs LoRA finetuning via trl SFTTrainer.

Modes:
  --export-only    Just export samples to jsonl (no training deps needed)
  --dry-run        Validate config + data shape, print planned LoRA config,
                   do NOT actually train (default; works without torch/peft)
  --train          Actually run LoRA finetuning (requires torch + peft; GPU
                   recommended, --cpu forces fp32 small-batch for debugging)

Environment:
  POSTGRES_URI      — DB connection (samples live in evaluator_samples)
  XHS_FT_BASE_MODEL — base model to finetune (default: Qwen/Qwen2.5-7B-Instruct)
  XHS_FT_OUT_DIR    — output dir for adapter (default: ./finetune_out)
  XHS_FT_MIN_SAMPLES— min samples to allow training (default: 50)

Usage:
  python scripts/finetune_evaluator.py --dry-run
  python scripts/finetune_evaluator.py --export-only --account-id acct1
  python scripts/finetune_evaluator.py --train            # GPU + deps
  python scripts/finetune_evaluator.py --train --cpu      # CPU debug

Out of scope: eval benchmarks vs base model, online continuous training.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

# Evaluator task routing (mirror backend/config/models.py TaskType.EVALUATION)
DEFAULT_BASE_MODEL = os.environ.get("XHS_FT_BASE_MODEL", "Qwen/Qwen2.5-7B-Instruct")
DEFAULT_OUT_DIR = os.environ.get("XHS_FT_OUT_DIR", "./finetune_out")
DEFAULT_MIN_SAMPLES = int(os.environ.get("XHS_FT_MIN_SAMPLES", "50"))

# LoRA hyperparams — conservative defaults for judge-style SFT
LORA_CONFIG = {
    "r": 16,
    "lora_alpha": 32,
    "lora_dropout": 0.05,
    "bias": "none",
    "task_type": "CAUSAL_LM",
    "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj"],
}
TRAIN_HYPERPARAMS = {
    "per_device_train_batch_size": 4,
    "gradient_accumulation_steps": 4,
    "num_train_epochs": 3,
    "learning_rate": 2e-4,
    "lr_scheduler_type": "cosine",
    "warmup_ratio": 0.03,
    "bf16": True,
}


async def fetch_samples(account_id: str | None, limit: int) -> list[dict[str, Any]]:
    """Fetch samples from DB; returns [] if DB unavailable."""
    from backend.db.evaluator_config import export_samples
    from backend.db.pool import is_pool_ready

    if not is_pool_ready():
        print("⚠ DB pool not ready — no samples fetched.", file=sys.stderr)
        return []
    return await export_samples(account_id, limit=limit)


def sample_to_jsonl(sample: dict[str, Any]) -> dict[str, Any]:
    """Convert one DB sample row to a chat-format training record.

    Instruction = evaluator judge task framing;
    Input = the evaluated content snapshot (title/body/hashtags/cta/visual) so
      the model learns content→score, not just score regurgitation;
    Output = the full recorded judgment (6-dim scores incl. bias_severity,
      rationale, issues, decision, bias_warning) — the reasoning signal SFT
      should learn, not bare numbers.
    Engagement (if back-filled) is attached as metadata, not part of the SFT
    target — it's a weak label for later reward/DPO stages.
    """
    dims = sample.get("dimensions") or []
    snapshot = sample.get("content_snapshot")
    # Legacy samples without a snapshot are marked incomplete so they can be
    # filtered out before training rather than silently producing input-less records.
    incomplete = not snapshot

    instruction = (
        "你是创作质量评审员。评估以下内容的 6 维质量"
        "（文案/视觉/合规/传播/受众/偏倚检测），给出各维度分数、理由、问题与决策。"
    )
    record: dict[str, Any] = {
        "instruction": instruction,
        "input": _render_content_input(snapshot) if snapshot else "",
        "output": _render_judgment_output(sample, dims),
        "history": [],
    }
    if incomplete:
        record["metadata"] = {"incomplete": True, "label_source": sample.get("label_source")}
        return record
    eng = sample.get("engagement")
    if eng:
        record["metadata"] = {"engagement": eng, "label_source": sample.get("label_source")}
    return record


def _render_content_input(snapshot: dict[str, Any]) -> str:
    """Render the content snapshot as the SFT input (what was judged)."""
    lines = [
        f"标题：{snapshot.get('title', '')}",
        f"正文：{snapshot.get('body', '')}",
        f"标签：{', '.join(snapshot.get('hashtags') or [])}",
        f"CTA：{snapshot.get('cta', '')}",
        f"语气：{snapshot.get('tone', '')}",
        f"封面prompt：{snapshot.get('cover_prompt', '')}",
        f"版式：{snapshot.get('layout_style', '')}",
        f"图片数：{snapshot.get('image_count', 0)}",
    ]
    for i, prompt in enumerate(snapshot.get("image_prompts") or [], 1):
        lines.append(f"图{i}：{prompt}")
    return "\n".join(lines)


def _render_judgment_output(sample: dict[str, Any], dims: list[dict[str, Any]]) -> str:
    """Render the full recorded judgment — the SFT target the model learns."""
    lines = [
        f"综合分：{sample.get('overall_score')}",
        f"决策：{sample.get('decision')}",
        "维度评分：",
    ]
    for d in dims:
        if not isinstance(d, dict):
            continue
        name = d.get("dimension", "")
        score = d.get("score", "")
        sev = d.get("bias_severity")
        sev_str = f"，bias_severity={sev}" if sev is not None else ""
        blocking = " [BLOCKING]" if d.get("is_blocking") else ""
        lines.append(f"- {name}：{score}{sev_str}{blocking}")
        rationale = d.get("rationale")
        if rationale:
            lines.append(f"  理由：{rationale}")
        issues = d.get("issues") or []
        for issue in issues[:3]:  # cap issues per dim — keep output bounded
            lines.append(f"  问题：{issue}")
    bias_warning = sample.get("bias_warning")
    if bias_warning:
        lines.append(f"偏倚预警：{bias_warning}")
    return "\n".join(lines)


def export_to_jsonl(samples: list[dict[str, Any]], out_path: Path) -> int:
    """Write samples as jsonl. Returns count written."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(sample_to_jsonl(s), ensure_ascii=False) + "\n")
    return len(samples)


def dry_run(samples: list[dict[str, Any]], account_id: str | None) -> int:
    """Validate data + print planned config. Exit 0 if viable, 1 if not."""
    print("═" * 60)
    print("RQGM Evaluator Finetune — DRY RUN")
    print("═" * 60)
    print(f"Account filter : {account_id or '(all)'}")
    print(f"Samples fetched: {len(samples)}")
    labeled = [s for s in samples if s.get("engagement")]
    complete = [s for s in samples if s.get("content_snapshot")]
    print(f"  with engagement label: {len(labeled)}")
    print(f"  with content snapshot (trainable): {len(complete)}")
    if len(complete) < len(samples):
        # ponytail: silent truncation reads as "all trainable" — surface the gap.
        print(
            f"  ⚠ {len(samples) - len(complete)} legacy samples lack content_snapshot "
            "(input-less, marked incomplete → filter before training)",
            file=sys.stderr,
        )
    print(f"  min required (XHS_FT_MIN_SAMPLES): {DEFAULT_MIN_SAMPLES}")

    print("\n─ Planned LoRA config ─")
    print(json.dumps(LORA_CONFIG, indent=2))
    print("\n─ Training hyperparams ─")
    print(json.dumps(TRAIN_HYPERPARAMS, indent=2))
    print(f"\nBase model : {DEFAULT_BASE_MODEL}")
    print(f"Output dir : {DEFAULT_OUT_DIR}")

    # ponytail: check training deps without importing them at module load
    missing = []
    for dep in ("torch", "transformers", "peft", "trl"):
        try:
            __import__(dep)
        except ImportError:
            missing.append(dep)
    print(f"\nTraining deps present: {not missing}")
    if missing:
        print(f"  missing: {', '.join(missing)} (install before --train)")

    if len(samples) < DEFAULT_MIN_SAMPLES:
        print(
            f"\n⚠ Only {len(samples)} samples (< {DEFAULT_MIN_SAMPLES}). "
            "Collect more before training.",
            file=sys.stderr,
        )
        return 1
    print(f"\n✓ {len(samples)} samples viable for training (run with --train when ready).")
    return 0


async def run_train(samples: list[dict[str, Any]], out_dir: Path, *, cpu: bool = False) -> int:
    """Actual LoRA finetune via trl SFTTrainer. Requires torch + peft + GPU (or --cpu).

    ponytail: full SFT flow — load base model, wrap with LoRA, train, save adapter
    + metrics. Code path is complete & executable; on a host without torch it
    exits 2 with an install hint, and --cpu forces fp32 small-batch for debugging.
    """
    try:
        import torch  # type: ignore[import-not-found]
        from datasets import load_dataset  # type: ignore[import-not-found]
        from peft import LoraConfig, get_peft_model  # type: ignore[import-not-found]
        from transformers import (  # type: ignore[import-not-found]
            AutoModelForCausalLM,
            AutoTokenizer,
        )
        from trl import SFTConfig, SFTTrainer  # type: ignore[import-not-found]
    except ImportError as e:
        print(
            f"✗ Training deps missing: {e}. Install torch/transformers/peft/trl "
            "and run on a GPU host (or pass --cpu for a small CPU debug run).",
            file=sys.stderr,
        )
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)
    data_path = out_dir / "train.jsonl"
    n = export_to_jsonl(samples, data_path)
    print(f"Exported {n} samples to {data_path}")
    if n == 0:
        print("✗ No samples to train on. Collect evaluations first.", file=sys.stderr)
        return 1

    device_map = "cpu" if cpu else "auto"
    dtype = torch.float32 if cpu else torch.bfloat16
    print(f"Loading base model {DEFAULT_BASE_MODEL} on {device_map} ({dtype})...")

    tokenizer = AutoTokenizer.from_pretrained(DEFAULT_BASE_MODEL, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        DEFAULT_BASE_MODEL,
        torch_dtype=dtype,
        device_map=device_map,
        trust_remote_code=True,
    )

    lora_config = LoraConfig(
        r=LORA_CONFIG["r"],
        lora_alpha=LORA_CONFIG["lora_alpha"],
        lora_dropout=LORA_CONFIG["lora_dropout"],
        bias=LORA_CONFIG["bias"],
        task_type=LORA_CONFIG["task_type"],
        target_modules=LORA_CONFIG["target_modules"],
    )
    model = get_peft_model(model, lora_config)

    # Build a chat-formatted dataset from the jsonl (instruction/input/output).
    dataset = load_dataset("json", data_files=str(data_path), split="train")

    def _format(example: dict[str, Any]) -> str:
        return (
            f"### 指令:\n{example.get('instruction', '')}\n\n"
            f"### 输入:\n{example.get('input', '')}\n\n"
            f"### 输出:\n{example.get('output', '')}"
        )

    cfg_kwargs = dict(TRAIN_HYPERPARAMS)
    if cpu:
        # ponytail: CPU debug profile — fp32, tiny batch, no bf16
        cfg_kwargs.update(
            per_device_train_batch_size=1,
            gradient_accumulation_steps=8,
            bf16=False,
            fp16=False,
        )
    sft_config = SFTConfig(
        output_dir=str(out_dir),
        max_seq_length=512,
        dataset_text_field="text",
        report_to="none",
        save_strategy="epoch",
        logging_steps=10,
        **{k: v for k, v in cfg_kwargs.items() if k in SFTConfig.__dataclass_fields__},
    )

    # Map to a 'text' field the SFTTrainer expects when dataset_text_field='text'.
    dataset = dataset.map(lambda ex: {"text": _format(ex)})

    trainer = SFTTrainer(
        model=model,
        args=sft_config,
        train_dataset=dataset,
        processing_class=tokenizer,
    )

    print(f"Training on {n} samples ({'CPU' if cpu else 'GPU'})...")
    train_result = trainer.train()

    adapter_path = out_dir / "adapter"
    trainer.save_model(str(adapter_path))
    tokenizer.save_pretrained(str(adapter_path))

    import json as _json

    metrics = {
        "samples": n,
        "global_step": train_result.global_step,
        "train_loss": float(train_result.training_loss),
        "base_model": DEFAULT_BASE_MODEL,
        "lora_config": LORA_CONFIG,
        "cpu": cpu,
    }
    (out_dir / "metrics.json").write_text(_json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"✓ Adapter saved to {adapter_path}")
    print(f"✓ metrics: loss={metrics['train_loss']:.4f} steps={metrics['global_step']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="RQGM evaluator finetune scaffold")
    ap.add_argument("--dry-run", action="store_true", help="validate config+data, no training")
    ap.add_argument("--export-only", action="store_true", help="just export samples to jsonl")
    ap.add_argument("--train", action="store_true", help="actually run LoRA finetune (needs GPU)")
    ap.add_argument("--cpu", action="store_true", help="force CPU fp32 small-batch (debug)")
    ap.add_argument("--account-id", default=None, help="filter samples by account")
    ap.add_argument("--limit", type=int, default=10000, help="max samples to fetch")
    ap.add_argument("--out", default=DEFAULT_OUT_DIR, help="output directory")
    args = ap.parse_args()

    out_dir = Path(args.out)
    samples = asyncio.run(fetch_samples(args.account_id, args.limit))

    if args.export_only:
        n = export_to_jsonl(samples, out_dir / "samples.jsonl")
        print(f"Exported {n} samples → {out_dir / 'samples.jsonl'}")
        return 0

    if args.train:
        return asyncio.run(run_train(samples, out_dir, cpu=args.cpu))

    # default: dry-run
    return dry_run(samples, args.account_id)


if __name__ == "__main__":
    sys.exit(main())
