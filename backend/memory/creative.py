"""Creative Memory — 三层创作记忆读写 + 行业基准.

Namespaces:
  accounts/{id}/style_dna          — 风格指纹
  accounts/{id}/conversion_playbook — 转化策略手册
  accounts/{id}/material_vault     — 优质素材库
  benchmarks/{niche}/              — 行业基准
"""

from __future__ import annotations

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
    """创作记忆 — 三层读写，创作即沉淀"""

    def __init__(self, account_id: str, store: BaseStore | None = None):
        self.account_id = account_id
        self._store = store
        self._available = store is not None

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
        self, query: str = "", limit: int = 3,
        *, keywords: list[str] | None = None, filter: dict[str, Any] | None = None,
    ) -> list[StyleDNA]:
        """召回匹配的风格指纹

        Args:
            query: 语义搜索查询
            keywords: 关键词过滤（所有关键词必须出现在条目的文本字段中）
            filter: 精确字段匹配过滤（如 {"tone": "治愈"}）
        """
        if not self._available:
            return self._default_styles()
        try:
            fetch_limit = limit * 2 if keywords else limit
            items = await self._store.asearch(  # type: ignore[union-attr]
                self.style_dna_ns, query=query or "style", limit=fetch_limit, filter=filter,
            )
            if keywords:
                items = _keyword_filter(items, keywords)
            results: list[StyleDNA] = [item.value for item in items[:limit]]  # type: ignore[misc]
            return results if results else self._default_styles()
        except Exception as e:
            logger.warning(f"recall_style failed: {e}")
            return self._default_styles()

    async def recall_plays(
        self, condition: str = "", niche: str = "", limit: int = 3,
        *, keywords: list[str] | None = None, filter: dict[str, Any] | None = None,
    ) -> list[ConversionPlay]:
        """召回匹配场景的转化策略

        Args:
            condition: 触发场景描述
            niche: 行业领域
            keywords: 关键词过滤
            filter: 精确字段匹配过滤（如 {"trigger_condition": "新品首发"}）
        """
        if not self._available:
            return []
        try:
            q = f"{condition} {niche}".strip() or "conversion"
            fetch_limit = limit * 2 if keywords else limit
            items = await self._store.asearch(  # type: ignore[union-attr]
                self.playbook_ns, query=q, limit=fetch_limit, filter=filter,
            )
            if keywords:
                items = _keyword_filter(items, keywords)
            return [item.value for item in items[:limit]]  # type: ignore[misc]
        except Exception as e:
            logger.warning(f"recall_plays failed: {e}")
            return []

    async def recall_materials(
        self, category: str = "", tags: list[str] | None = None, limit: int = 5,
        *, keywords: list[str] | None = None, filter: dict[str, Any] | None = None,
    ) -> list[MaterialEntry]:
        """召回优质素材（按 weight * relevance 排序）

        Args:
            category: 素材类别
            tags: 标签列表
            keywords: 关键词过滤
            filter: 精确字段匹配过滤（如 {"category": "标题模板"}）
        """
        if not self._available:
            return []
        try:
            q = " ".join([v for v in [category] + (tags or []) if v]) or "material"
            fetch_limit = limit * 2 if keywords else limit
            items = await self._store.asearch(  # type: ignore[union-attr]
                self.vault_ns, query=q, limit=fetch_limit, filter=filter,
            )
            if keywords:
                items = _keyword_filter(items, keywords)
            # 按 weight 排序（asearch 已按 relevance 排，这里叠加 weight）
            entries: list[MaterialEntry] = [item.value for item in items]  # type: ignore[misc]
            entries.sort(key=lambda e: e.get("weight", 1.0), reverse=True)
            return entries[:limit]
        except Exception as e:
            logger.warning(f"recall_materials failed: {e}")
            return []

    async def recall_benchmark(self, niche: str) -> NicheBenchmark | None:
        """召回行业基准"""
        if not self._available:
            return None
        try:
            ns = self.benchmark_ns(niche)
            items = await self._store.asearch(  # type: ignore[union-attr]
                ns, query=niche, limit=1
            )
            result: NicheBenchmark | None = items[0].value if items else None  # type: ignore[assignment]
            return result
        except Exception as e:
            logger.warning(f"recall_benchmark failed: {e}")
            return None

    # ── 沉淀：创作后写入 ──

    async def deposit_style(self, style: StyleDNA) -> None:
        """沉淀风格指纹（同风格合并，累加 sample_count）"""
        if not self._available:
            return
        try:
            existing = await self._find_similar_style(style)
            if existing:
                key, old = existing
                merged = self._merge_style(old, style)
                # Write the existing key back so caller can read style_id
                style["style_id"] = key
                await self._store.aput(self.style_dna_ns, key=key, value=merged)  # type: ignore[union-attr]
            else:
                key = style.get("style_id") or str(uuid.uuid4())
                style["style_id"] = key
                style.setdefault("sample_count", 1)
                style.setdefault("last_used", datetime.now(UTC).isoformat())
                await self._store.aput(self.style_dna_ns, key=key, value=style)  # type: ignore[union-attr,arg-type]
        except Exception as e:
            logger.warning(f"deposit_style failed: {e}")

    async def deposit_play(self, play: ConversionPlay) -> None:
        """沉淀转化策略"""
        if not self._available:
            return
        try:
            key = play.get("play_id") or str(uuid.uuid4())
            play["play_id"] = key
            play.setdefault("proven_count", 0)
            play.setdefault("last_proven", datetime.now(UTC).isoformat())
            await self._store.aput(self.playbook_ns, key=key, value=play)  # type: ignore[union-attr,arg-type]
        except Exception as e:
            logger.warning(f"deposit_play failed: {e}")

    async def deposit_material(self, entry: MaterialEntry) -> None:
        """沉淀优质素材"""
        if not self._available:
            return
        try:
            key = entry.get("material_id") or str(uuid.uuid4())
            entry["material_id"] = key
            entry.setdefault("reuse_count", 0)
            entry.setdefault("effectiveness", 0.5)
            entry.setdefault("weight", 1.0)
            entry.setdefault("created_at", datetime.now(UTC).isoformat())
            await self._store.aput(self.vault_ns, key=key, value=entry)  # type: ignore[union-attr,arg-type]
        except Exception as e:
            logger.warning(f"deposit_material failed: {e}")

    async def deposit_benchmark(self, niche: str, benchmark: NicheBenchmark) -> None:
        """沉淀行业基准"""
        if not self._available:
            return
        try:
            ns = self.benchmark_ns(niche)
            benchmark["updated_at"] = datetime.now(UTC).isoformat()
            await self._store.aput(ns, key=niche, value=benchmark)  # type: ignore[union-attr,arg-type]
        except Exception as e:
            logger.warning(f"deposit_benchmark failed: {e}")

    # ── 校准：analyst 回写 ──

    async def calibrate(self, payload: CalibrationPayload) -> dict[str, int]:
        """根据校准数据更新三个 namespace.

        Uses aget(key=id) for direct ID lookup instead of asearch(query=id),
        which is more reliable and avoids missing items when semantic search
        is disabled or data volume is large.

        Returns update stats: {"styles": N, "plays": N, "materials": N}
        """
        stats = {"styles": 0, "plays": 0, "materials": 0}
        if not self._available:
            return stats

        # 1. 更新 Style DNA engagement_rate
        style_id = payload.get("style_id", "")
        if style_id:
            try:
                item = await self._store.aget(  # type: ignore[union-attr]
                    self.style_dna_ns, key=style_id
                )
                if item is not None:
                    old = item.value
                    old_rate = old.get("engagement_rate", 0.0)
                    new_rate = payload.get("actual_engagement_rate", old_rate)
                    n = old.get("sample_count", 1)
                    old["engagement_rate"] = round((old_rate * n + new_rate) / (n + 1), 4)
                    old["sample_count"] = n + 1
                    old["last_used"] = datetime.now(UTC).isoformat()
                    await self._store.aput(  # type: ignore[union-attr]
                        self.style_dna_ns, key=style_id, value=old
                    )
                    stats["styles"] = 1
            except Exception as e:
                logger.warning(f"calibrate style failed: {e}")

        # 2. 更新 Conversion Playbook proven_count
        play_id = payload.get("play_id", "")
        if play_id:
            try:
                item = await self._store.aget(  # type: ignore[union-attr]
                    self.playbook_ns, key=play_id
                )
                if item is not None:
                    old = item.value
                    if payload.get("play_success", False):
                        old["proven_count"] = old.get("proven_count", 0) + 1
                        old["last_proven"] = datetime.now(UTC).isoformat()
                    await self._store.aput(  # type: ignore[union-attr]
                        self.playbook_ns, key=play_id, value=old
                    )
                    stats["plays"] = 1
            except Exception as e:
                logger.warning(f"calibrate play failed: {e}")

        # 3. 更新 Material Vault effectiveness + 软降权
        material_effectiveness = payload.get("material_effectiveness", {})
        for mid, eff in material_effectiveness.items():
            try:
                item = await self._store.aget(  # type: ignore[union-attr]
                    self.vault_ns, key=mid
                )
                if item is not None:
                    old = item.value
                    old["effectiveness"] = eff
                    old["reuse_count"] = old.get("reuse_count", 0) + 1
                    if eff < EFFECTIVENESS_THRESHOLD:
                        old["weight"] = round(old.get("weight", 1.0) * DOWNGRADE_FACTOR, 4)
                    await self._store.aput(  # type: ignore[union-attr]
                        self.vault_ns, key=mid, value=old
                    )
                    stats["materials"] += 1
            except Exception as e:
                logger.warning(f"calibrate material {mid} failed: {e}")

        return stats

    # ── 内部方法 ──

    async def _find_similar_style(self, style: StyleDNA) -> tuple[str, dict[str, Any]] | None:
        """查找相似风格（同 tone + visual_style 视为同风格）"""
        tone = style.get("tone", "")
        visual = style.get("visual_style", "")
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
                parts.append(f"  文风={tone} 视觉={visual} 互动率={rate} 采样={n}")
                if s.get("voice_patterns"):
                    parts.append(f"  常用句式: {', '.join(s['voice_patterns'][:3])}")
                if s.get("color_palette"):
                    parts.append(f"  偏好色系: {', '.join(s['color_palette'][:3])}")

        if plays:
            parts.append("转化策略：")
            for p in plays[:2]:
                parts.append(
                    f"  场景={p.get('trigger_condition', '')} "
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
