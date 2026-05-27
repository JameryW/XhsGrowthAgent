"""Optimization service - orchestrates pre-publish optimization tools."""

from typing import Any
from xhs_growth.tools.optimization import extract_title_features
from xhs_growth.state.schema import XHSGrowthState


class OptimizationService:
    """优化流程编排服务"""

    def analyze_titles(self, draft_title: str, viral_titles: list[str]) -> dict[str, Any]:
        """分析标题对比"""
        features = [extract_title_features(t) for t in viral_titles]
        return self._compare_features(draft_title, features)

    def _compare_features(self, draft: str, viral_features: list[dict]) -> dict[str, Any]:
        """对比标题特征"""
        draft_features = extract_title_features(draft)
        gaps = []

        # 对比长度
        avg_viral_length = sum(f.get("length", 0) for f in viral_features) / len(viral_features)
        if draft_features.get("length", 0) < avg_viral_length * 0.8:
            gaps.append({
                "dimension": "title",
                "description": "标题长度偏短",
                "severity": "medium"
            })

        # 对比关键词
        viral_keywords = set()
        for f in viral_features:
            viral_keywords.update(f.get("keywords", []))
        draft_keywords = set(draft_features.get("keywords", []))
        missing_keywords = viral_keywords - draft_keywords
        if missing_keywords:
            gaps.append({
                "dimension": "title",
                "description": f"缺少爆款关键词: {list(missing_keywords)[:5]}",
                "severity": "high"
            })

        return {"gaps": gaps, "draft_features": draft_features}