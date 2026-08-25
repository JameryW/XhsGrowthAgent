"""Creative Memory — 三层创作记忆读写 + 行业基准.

Namespaces:
  accounts/{id}/style_dna          — 风格指纹
  accounts/{id}/conversion_playbook — 转化策略手册
  accounts/{id}/material_vault     — 优质素材库
  benchmarks/{niche}/              — 行业基准
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from langgraph.store.base import BaseStore

from backend.memory.store import _keyword_filter
from backend.memory.types import (
    CalibrationPayload,
    ConversionPlay,
    MaterialEntry,
    NicheBenchmark,
    StyleDNA,
)

logger = logging.getLogger("xhs_growth.memory.creative")

# 冷启动阈值
MIN_SAMPLES = 5

# 软降权参数
EFFECTIVENESS_THRESHOLD = 0.3
DOWNGRADE_FACTOR = 0.8


class CreativeMemory:
    """创作记忆 — 三层读写，创作即沉淀.

    Durable source of truth: ``backend.db.creative_memory`` (Postgres or
    process-local fallback). Optional LangGraph ``BaseStore`` is dual-written
    for semantic search when present. Deposits work even when ``store is None``.
    """

    def __init__(self, account_id: str, store: BaseStore | None = None):
        self.account_id = (account_id or "").strip() or "default"
        self._store = store
        # Always "available" via durable DB layer (even without graph store)
        self._available = True
        self._has_store = store is not None

    # ── Namespace 属性 ──

    @property
    def style_dna_ns(self) -> tuple[str, str, str]:
        return ("accounts", self.account_id, "style_dna")

    @property
    def playbook_ns(self) -> tuple[str, str, str]:
        return ("accounts", self.account_id, "conversion_playbook")

    @property
    def vault_ns(self) -> tuple[str, str, str]:
        return ("accounts", self.account_id, "material_vault")

    @staticmethod
    def benchmark_ns(niche: str) -> tuple[str, str]:
        return ("benchmarks", niche)

    # ── 读取：创作前召回 ──

    async def recall_style(
        self,
        query: str = "",
        limit: int = 3,
        *,
        keywords: list[str] | None = None,
        filter: dict[str, Any] | None = None,
    ) -> list[StyleDNA]:
        """召回匹配的风格指纹（持久化优先，store 语义检索补充）"""
        results: list[StyleDNA] = []
        # 1) Durable rows first (survive restarts / CLI import without store)
        try:
            from backend.db import creative_memory as cm_db

            durable = await cm_db.list_styles(self.account_id, limit=max(limit * 2, 10))
            results.extend(durable)  # type: ignore[arg-type]
        except Exception as e:
            logger.warning(f"recall_style durable failed: {e}")

        # 2) Optional semantic search on LangGraph store
        if self._has_store:
            try:
                fetch_limit = limit * 2 if keywords else limit
                items = await self._store.asearch(  # type: ignore[union-attr]
                    self.style_dna_ns,
                    query=query or "style",
                    limit=fetch_limit,
                    filter=filter,
                )
                if keywords:
                    items = _keyword_filter(items, keywords)
                for item in items:
                    v = item.value
                    if isinstance(v, dict):
                        results.append(v)  # type: ignore[arg-type]
            except Exception as e:
                logger.warning(f"recall_style store failed: {e}")

        # Deduplicate by style_id, drop empty
        by_id: dict[str, StyleDNA] = {}
        for s in results:
            if not isinstance(s, dict):
                continue
            if filter and any(s.get(k) != v for k, v in filter.items()):
                continue
            if keywords:
                blob = " ".join(str(x) for x in s.values()).lower()
                if not all(str(k).lower() in blob for k in keywords):
                    continue
            sid = str(s.get("style_id") or "")
            if not sid:
                continue
            # Prefer higher engagement / sample when merging duplicates
            prev = by_id.get(sid)
            if prev is None or float(s.get("sample_count") or 0) >= float(
                prev.get("sample_count") or 0
            ):
                by_id[sid] = s

        ranked = sorted(
            by_id.values(),
            key=lambda x: (
                float(x.get("engagement_rate") or 0),
                int(x.get("sample_count") or 0),
            ),
            reverse=True,
        )
        # Exclude cold defaults when real account styles exist
        real = [s for s in ranked if not str(s.get("style_id", "")).startswith("default_")]
        chosen = real[:limit] if real else ranked[:limit]
        return chosen if chosen else self._default_styles()

    async def recall_plays(
        self,
        condition: str = "",
        niche: str = "",
        limit: int = 3,
        *,
        keywords: list[str] | None = None,
        filter: dict[str, Any] | None = None,
    ) -> list[ConversionPlay]:
        """召回匹配场景的转化策略"""
        results: list[ConversionPlay] = []
        try:
            from backend.db import creative_memory as cm_db

            # Prefer niche-matched + universal (empty niche) plays. If that yields
            # nothing, fall back to all plays so topic-tag misuse still surfaces.
            durable = await cm_db.list_plays(self.account_id, niche=niche, limit=max(limit * 2, 10))
            if not durable and niche:
                durable = await cm_db.list_plays(
                    self.account_id, niche="", limit=max(limit * 2, 10)
                )
            results.extend(durable)  # type: ignore[arg-type]
        except Exception as e:
            logger.warning(f"recall_plays durable failed: {e}")

        if self._has_store:
            try:
                q = f"{condition} {niche}".strip() or "conversion"
                fetch_limit = limit * 2 if keywords else limit
                items = await self._store.asearch(  # type: ignore[union-attr]
                    self.playbook_ns,
                    query=q,
                    limit=fetch_limit,
                    filter=filter,
                )
                if keywords:
                    items = _keyword_filter(items, keywords)
                for item in items:
                    if isinstance(item.value, dict):
                        results.append(item.value)  # type: ignore[arg-type]
            except Exception as e:
                logger.warning(f"recall_plays store failed: {e}")

        by_id: dict[str, ConversionPlay] = {}
        for p in results:
            if not isinstance(p, dict):
                continue
            pid = str(p.get("play_id") or "")
            if not pid:
                continue
            by_id[pid] = p
        ranked = sorted(
            by_id.values(),
            key=lambda x: float(x.get("avg_engagement_rate") or 0),
            reverse=True,
        )
        return ranked[:limit]

    async def recall_materials(
        self,
        category: str = "",
        tags: list[str] | None = None,
        limit: int = 5,
        *,
        keywords: list[str] | None = None,
        filter: dict[str, Any] | None = None,
    ) -> list[MaterialEntry]:
        """召回优质素材（按 weight 排序）"""
        results: list[MaterialEntry] = []
        try:
            from backend.db import creative_memory as cm_db

            durable = await cm_db.list_materials(
                self.account_id,
                category=category,
                tags=tags,
                limit=max(limit * 2, 10),
            )
            results.extend(durable)  # type: ignore[arg-type]
        except Exception as e:
            logger.warning(f"recall_materials durable failed: {e}")

        if self._has_store:
            try:
                q = " ".join([v for v in [category] + (tags or []) if v]) or "material"
                fetch_limit = limit * 2 if keywords else limit
                items = await self._store.asearch(  # type: ignore[union-attr]
                    self.vault_ns,
                    query=q,
                    limit=fetch_limit,
                    filter=filter,
                )
                if keywords:
                    items = _keyword_filter(items, keywords)
                for item in items:
                    if isinstance(item.value, dict):
                        results.append(item.value)  # type: ignore[arg-type]
            except Exception as e:
                logger.warning(f"recall_materials store failed: {e}")

        by_id: dict[str, MaterialEntry] = {}
        for m in results:
            if not isinstance(m, dict):
                continue
            if category and (m.get("category") or "") != category:
                continue
            mid = str(m.get("material_id") or "")
            if not mid:
                continue
            by_id[mid] = m
        ranked = sorted(
            by_id.values(),
            key=lambda e: float(e.get("weight", 1.0) or 1.0),
            reverse=True,
        )
        return ranked[:limit]

    async def recall_benchmark(self, niche: str) -> NicheBenchmark | None:
        """召回行业基准"""
        try:
            from backend.db import creative_memory as cm_db

            durable = await cm_db.get_benchmark(niche)
            if durable:
                return durable  # type: ignore[return-value]
        except Exception as e:
            logger.warning(f"recall_benchmark durable failed: {e}")

        if not self._has_store:
            return None
        try:
            ns = self.benchmark_ns(niche)
            items = await self._store.asearch(  # type: ignore[union-attr]
                ns, query=niche, limit=1
            )
            result: NicheBenchmark | None = items[0].value if items else None  # type: ignore[assignment]
            return result
        except Exception as e:
            logger.warning(f"recall_benchmark store failed: {e}")
            return None

    # ── 沉淀：创作后写入 ──

    async def deposit_style(self, style: StyleDNA) -> None:
        """沉淀风格指纹（同风格合并，累加 sample_count）— 持久化 + 可选 store"""
        try:
            from backend.db import creative_memory as cm_db

            tone = str(style.get("tone") or "")
            visual = str(style.get("visual_style") or "")
            async with (
                cm_db.get_style_merge_lock(self.account_id, tone, visual),
                cm_db.style_merge_transaction(self.account_id, tone, visual) as conn,
            ):
                existing = await self._find_similar_style(style, conn=conn)
                if existing:
                    key, old = existing
                    payload = self._merge_style(old, style)
                else:
                    key = style.get("style_id") or str(uuid.uuid4())
                    style.setdefault("sample_count", 1)
                    style.setdefault("last_used", datetime.now(UTC).isoformat())
                    payload = dict(style)
                style["style_id"] = key
                payload["style_id"] = key
                await cm_db.upsert_style(self.account_id, key, payload, conn=conn)
            await self._sync_style_store(key, payload)
        except Exception as e:
            logger.warning(f"deposit_style failed: {e}")

    async def deposit_play(self, play: ConversionPlay) -> None:
        """沉淀转化策略 — 持久化 + 可选 store"""
        try:
            key = play.get("play_id") or str(uuid.uuid4())
            play["play_id"] = key
            play.setdefault("proven_count", 0)
            play.setdefault("last_proven", datetime.now(UTC).isoformat())
            await self._persist_play(key, dict(play))
        except Exception as e:
            logger.warning(f"deposit_play failed: {e}")

    async def deposit_material(self, entry: MaterialEntry) -> None:
        """沉淀优质素材 — 持久化 + 可选 store"""
        try:
            key = entry.get("material_id") or str(uuid.uuid4())
            entry["material_id"] = key
            entry.setdefault("reuse_count", 0)
            entry.setdefault("effectiveness", 0.5)
            entry.setdefault("weight", 1.0)
            entry.setdefault("created_at", datetime.now(UTC).isoformat())
            await self._persist_material(key, dict(entry))
        except Exception as e:
            logger.warning(f"deposit_material failed: {e}")

    async def deposit_benchmark(self, niche: str, benchmark: NicheBenchmark) -> None:
        """沉淀行业基准 — 持久化 + 可选 store"""
        try:
            from backend.db import creative_memory as cm_db

            benchmark["updated_at"] = datetime.now(UTC).isoformat()
            await cm_db.upsert_benchmark(niche, dict(benchmark))
            if self._has_store:
                try:
                    ns = self.benchmark_ns(niche)
                    await self._store.aput(ns, key=niche, value=benchmark)  # type: ignore[union-attr,arg-type]
                except Exception as e:
                    logger.warning("benchmark store dual-write failed (durable ok): %s", e)
        except Exception as e:
            logger.warning(f"deposit_benchmark failed: {e}")

    async def _persist_style(self, key: str, payload: dict[str, Any]) -> None:
        from backend.db import creative_memory as cm_db

        # Durable write is authoritative; LangGraph store dual-write is best-effort.
        await cm_db.upsert_style(self.account_id, key, payload)
        await self._sync_style_store(key, payload)

    async def _sync_style_store(self, key: str, payload: dict[str, Any]) -> None:
        """Best-effort semantic-store mirror after the durable style write commits."""
        if self._has_store:
            try:
                await self._store.aput(self.style_dna_ns, key=key, value=payload)  # type: ignore[union-attr]
            except Exception as e:
                logger.warning("style DNA store dual-write failed (durable ok): %s", e)

    async def _persist_play(self, key: str, payload: dict[str, Any]) -> None:
        from backend.db import creative_memory as cm_db

        await cm_db.upsert_play(self.account_id, key, payload)
        if self._has_store:
            try:
                await self._store.aput(self.playbook_ns, key=key, value=payload)  # type: ignore[union-attr]
            except Exception as e:
                logger.warning("playbook store dual-write failed (durable ok): %s", e)

    async def _persist_material(self, key: str, payload: dict[str, Any]) -> None:
        from backend.db import creative_memory as cm_db

        await cm_db.upsert_material(self.account_id, key, payload)
        if self._has_store:
            try:
                await self._store.aput(self.vault_ns, key=key, value=payload)  # type: ignore[union-attr]
            except Exception as e:
                logger.warning("material store dual-write failed (durable ok): %s", e)

    # ── 校准：analyst 回写 ──

    async def calibrate(self, payload: CalibrationPayload) -> dict[str, int]:
        """根据校准数据更新三个 namespace（持久化 + 可选 store）.

        Uses durable get_style/get_play/get_material for ID lookup, with store
        aget as secondary. More reliable when semantic search is disabled.

        Returns update stats: {"styles": N, "plays": N, "materials": N}

        The three namespace updates (style / play / material) are independent —
        distinct IDs, distinct namespaces, no shared state. Gathered so the
        fire-and-forget calibration task releases its DB/store connections
        sooner. Each helper has its own try/except (swallow + log), so a failure
        in one namespace does not abort the others (no _safe_* wrapper needed).
        """
        styles, plays, materials = await asyncio.gather(
            self._calibrate_style(payload),
            self._calibrate_play(payload),
            self._calibrate_materials(payload),
        )
        return {"styles": styles, "plays": plays, "materials": materials}

    async def _calibrate_style(self, payload: CalibrationPayload) -> int:
        """Update Style DNA engagement_rate. Returns 1 on update, 0 otherwise."""
        from backend.db import creative_memory as cm_db

        style_id = payload.get("style_id", "")
        if not style_id:
            return 0
        try:
            old = await cm_db.get_style(self.account_id, style_id)
            if old is None and self._has_store:
                item = await self._store.aget(  # type: ignore[union-attr]
                    self.style_dna_ns, key=style_id
                )
                if item is not None:
                    old = item.value
            if old is not None:
                old_rate = old.get("engagement_rate", 0.0)
                new_rate = payload.get("actual_engagement_rate", old_rate)
                n = old.get("sample_count", 1)
                old["engagement_rate"] = round((old_rate * n + new_rate) / (n + 1), 4)
                old["sample_count"] = n + 1
                old["last_used"] = datetime.now(UTC).isoformat()
                await self._persist_style(style_id, dict(old))
                return 1
        except Exception as e:
            logger.warning(f"calibrate style failed: {e}")
        return 0

    async def _calibrate_play(self, payload: CalibrationPayload) -> int:
        """Update Conversion Playbook proven_count. Returns 1 on update, 0 otherwise."""
        from backend.db import creative_memory as cm_db

        play_id = payload.get("play_id", "")
        if not play_id:
            return 0
        try:
            old = await cm_db.get_play(self.account_id, play_id)
            if old is None and self._has_store:
                item = await self._store.aget(  # type: ignore[union-attr]
                    self.playbook_ns, key=play_id
                )
                if item is not None:
                    old = item.value
            if old is not None:
                if payload.get("play_success", False):
                    old["proven_count"] = old.get("proven_count", 0) + 1
                    old["last_proven"] = datetime.now(UTC).isoformat()
                await self._persist_play(play_id, dict(old))
                return 1
        except Exception as e:
            logger.warning(f"calibrate play failed: {e}")
        return 0

    async def _calibrate_materials(self, payload: CalibrationPayload) -> int:
        """Update Material Vault effectiveness + soft-downgrade for each material.

        Materials are independent (distinct IDs in the vault namespace), so the
        per-item read-then-write is gathered. Each item has its own try/except
        (swallow + log), so one failing material does not abort the rest.
        Returns the count of materials updated.
        """
        from backend.db import creative_memory as cm_db

        material_effectiveness = payload.get("material_effectiveness", {})
        if not material_effectiveness:
            return 0

        async def _update_one(mid: str, eff: float) -> int:
            try:
                old = await cm_db.get_material(self.account_id, mid)
                if old is None and self._has_store:
                    item = await self._store.aget(  # type: ignore[union-attr]
                        self.vault_ns, key=mid
                    )
                    if item is not None:
                        old = item.value
                if old is not None:
                    old["effectiveness"] = eff
                    old["reuse_count"] = old.get("reuse_count", 0) + 1
                    if eff < EFFECTIVENESS_THRESHOLD:
                        old["weight"] = round(old.get("weight", 1.0) * DOWNGRADE_FACTOR, 4)
                    await self._persist_material(mid, dict(old))
                    return 1
            except Exception as e:
                logger.warning(f"calibrate material {mid} failed: {e}")
            return 0

        results = await asyncio.gather(
            *(_update_one(mid, eff) for mid, eff in material_effectiveness.items())
        )
        return sum(results)

    # ── 内部方法 ──

    async def _find_similar_style(
        self, style: StyleDNA, *, conn: Any | None = None
    ) -> tuple[str, dict[str, Any]] | None:
        """查找相似风格（同 tone + visual_style 视为同风格）"""
        tone = style.get("tone", "")
        visual = style.get("visual_style", "")
        if not tone and not visual:
            return None
        # Durable exact match first
        try:
            from backend.db import creative_memory as cm_db

            hit = await cm_db.find_style_by_tone_visual(self.account_id, tone, visual, conn=conn)
            if hit:
                return hit
        except Exception as e:
            logger.debug("find_similar durable failed: %s", e)

        if not self._has_store:
            return None
        q = f"{tone} {visual}".strip()
        if not q:
            return None
        items = await self._store.asearch(self.style_dna_ns, query=q, limit=5)  # type: ignore[union-attr]
        for item in items:
            v = item.value
            if v.get("tone") == tone and v.get("visual_style") == visual:
                return (item.key, v)
        return None

    @staticmethod
    def _merge_style(old: dict[str, Any], new: StyleDNA) -> dict[str, Any]:
        """合并同风格 — 加权平均 engagement_rate，累加 sample_count"""
        n_old = old.get("sample_count", 1)
        n_new = new.get("sample_count", 1)
        total = n_old + n_new

        rate_old = old.get("engagement_rate", 0.0)
        rate_new = new.get("engagement_rate", 0.0)
        merged_rate = round((rate_old * n_old + rate_new * n_new) / total, 4)

        merged: dict[str, Any] = {**old}
        merged["engagement_rate"] = merged_rate
        merged["sample_count"] = total
        merged["last_used"] = datetime.now(UTC).isoformat()

        # 合并 voice_patterns（去重）
        old_patterns = old.get("voice_patterns", [])
        new_patterns = new.get("voice_patterns", [])
        merged["voice_patterns"] = list(dict.fromkeys(old_patterns + new_patterns))

        # 合并 color_palette（去重）
        old_colors = old.get("color_palette", [])
        new_colors = new.get("color_palette", [])
        merged["color_palette"] = list(dict.fromkeys(old_colors + new_colors))

        return merged

    @staticmethod
    def _default_styles() -> list[StyleDNA]:
        """冷启动默认风格指纹（从 style_library 默认配置映射）"""
        return [
            StyleDNA(
                style_id="default_warm",
                tone="治愈",
                voice_patterns=["你有没有发现...", "今天分享..."],
                visual_style="温暖治愈",
                color_palette=["#FFE4E1", "#FFDAB9", "#FFFACD"],
                layout_preference="拼贴",
                emoji_usage="克制",
                hashtag_style="精准少而美",
                engagement_rate=0.0,
                sample_count=0,
                last_used="",
            ),
            StyleDNA(
                style_id="default_minimal",
                tone="专业",
                voice_patterns=["3个方法...", "建议..."],
                visual_style="现代简约",
                color_palette=["#FFFFFF", "#F5F5F5", "#333333"],
                layout_preference="网格",
                emoji_usage="无",
                hashtag_style="精准少而美",
                engagement_rate=0.0,
                sample_count=0,
                last_used="",
            ),
            StyleDNA(
                style_id="default_vibrant",
                tone="活泼",
                voice_patterns=["姐妹们！", "绝绝子..."],
                visual_style="活力青春",
                color_palette=["#FF6B6B", "#4ECDC4", "#FFE66D"],
                layout_preference="单焦点",
                emoji_usage="重度",
                hashtag_style="广撒网",
                engagement_rate=0.0,
                sample_count=0,
                last_used="",
            ),
        ]

    def build_creative_context(
        self,
        styles: list[StyleDNA],
        plays: list[ConversionPlay],
        materials: list[MaterialEntry],
        benchmark: NicheBenchmark | None = None,
    ) -> str:
        """将召回的 memory 构建为 LLM 可消费的上下文文本"""
        parts: list[str] = []

        if styles:
            parts.append("风格指纹：")
            for s in styles[:2]:  # 最多 2 个
                tone = s.get("tone", "")
                visual = s.get("visual_style", "")
                rate = s.get("engagement_rate", "N/A")
                n = s.get("sample_count", 0)
                sid = s.get("style_id", "") or s.get("id", "")
                id_part = f" id={sid} " if sid else " "
                parts.append(f" {id_part}文风={tone} 视觉={visual} 互动率={rate} 采样={n}")
                if s.get("voice_patterns"):
                    parts.append(f"  常用句式: {', '.join(s['voice_patterns'][:3])}")
                if s.get("color_palette"):
                    parts.append(f"  偏好色系: {', '.join(s['color_palette'][:3])}")

        if plays:
            parts.append("转化策略：")
            for p in plays[:2]:
                pid = p.get("play_id", "") or p.get("id", "")
                pid_part = f" id={pid} " if pid else " "
                parts.append(
                    f"{pid_part} 场景={p.get('trigger_condition', '')} "
                    f"标题公式={p.get('title_formula', '')} "
                    f"验证={p.get('proven_count', 0)}次 "
                    f"互动率={p.get('avg_engagement_rate', 'N/A')}"
                )
                if p.get("opening_hook"):
                    parts.append(f"  开头钩子: {p['opening_hook']}")

        if materials:
            parts.append("优质素材：")
            for m in materials[:3]:
                parts.append(
                    f"  [{m.get('category', '')}] {m.get('content', '')[:50]} "
                    f"效果={m.get('effectiveness', 'N/A')}"
                )

        if benchmark:
            parts.append("行业基准：")
            if benchmark.get("trending_formulas"):
                parts.append(f"  热门标题公式: {', '.join(benchmark['trending_formulas'][:3])}")
            if benchmark.get("peak_posting_hours"):
                parts.append(f"  高峰时段: {benchmark['peak_posting_hours']}")
            if benchmark.get("top_styles"):
                top = benchmark["top_styles"][:2]
                parts.append(f"  热门风格: {', '.join(t.get('style_name', '') for t in top)}")

        return "\n".join(parts) if parts else ""


__all__ = ["CreativeMemory"]
