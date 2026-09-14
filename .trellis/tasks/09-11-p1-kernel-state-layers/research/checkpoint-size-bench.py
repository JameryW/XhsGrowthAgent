"""Checkpoint size benchmark for P1a (prd: 母婴长任务模拟, S 前后对比).

Why
    info.md acceptance: "checkpoint 单 superstep 序列化体积显著下降".  The prd
    asks for a mother & baby long-task simulation whose per-superstep
    serialized size is compared before vs after P1a, with the report written
    into the task's research/ directory.

Method
    - One "mother & baby" long task as an ordered list of supersteps (the node
      writes of a trend-mode run plus the optimization / ripple / blogger
      tail), mirroring the real pipeline write order.
    - Two shapes over the *same* business data:
        pre-P1a  — every body inline, telemetry (performance_log) inline and
                   re-serialized by every superstep, dead keys (messages /
                   content_history) present-but-empty exactly as pre-P1a code
                   initialised them.
        post-P1a — refable bodies replaced by real ArtifactRefs (built with
                   backend.state.artifacts.make_ref, the production write
                   seam), meta keys kept (versions_meta / blogger_notes_meta /
                   trend_summary), telemetry gone (S2: Event store), dead keys
                   gone (S1: they never carried bytes — see the report).
    - Size of one superstep = len(JsonPlusSerializer().dumps_typed(values)[1]):
      the exact code path every saver runs on channel_values (msgpack,
      langgraph-checkpoint 4.1.1).
    - Cumulative bytes = sum over supersteps: LangGraph checkpoints are full
      snapshots with no pruning (persistence-inventory.md), so this is what
      the checkpoint table actually accumulates.

The script is deterministic (fixed timestamps, fixed content).  Run from the
repo root with the project venv:

    python .trellis/tasks/09-11-p1-kernel-state-layers/research/checkpoint-size-bench.py

Output: a markdown report on stdout (pasted into checkpoint-size-bench.md).
"""

from __future__ import annotations

import json
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT))

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer  # noqa: E402

from backend.state.artifacts import (  # noqa: E402
    REFABLE_FIELDS,
    blogger_notes_meta_of,
    make_ref,
    trend_summary_of,
    versions_meta_of,
)

FIXED_TS = "2026-09-14T10:00:00+00:00"
_THREAD = "t-bench-muying"

# ── synthetic mother & baby business data ────────────────────────────────────


def _hot_topics() -> list[dict[str, Any]]:
    rows = [
        ("新生儿睡眠倒退怎么破", 92.5),
        ("一岁宝宝辅食黑名单", 88.1),
        ("纸尿裤尺码对照表", 85.3),
        ("宝宝湿疹护理避坑", 81.9),
        ("待产包最全清单", 79.4),
        ("婴儿抚触操教程", 76.8),
        ("混合喂养怎么安排", 73.2),
        ("宝宝爬行训练", 70.6),
        ("母婴好物平价替代", 68.9),
        ("断夜奶实战记录", 65.1),
    ]
    return [
        {
            "topic": topic,
            "heat_score": score,
            "heat_percentage": score,
            "growth_rate": round(score / 10, 2),
            "related_keywords": [f"{topic[:4]}攻略", f"{topic[:4]}避坑", f"{topic[:4]}测评"],
        }
        for topic, score in rows
    ]


def _keywords() -> list[str]:
    base = [
        "待产包",
        "辅食表",
        "纸尿裤",
        "湿疹",
        "夜奶",
        "睡眠倒退",
        "抚触操",
        "混合喂养",
        "爬行期",
        "平价好物",
        "母婴实测",
        "新手妈妈",
        "月子",
        "奶瓶",
        "婴儿车",
    ]
    return base + [f"{item}2026" for item in base]


def _competitors() -> list[dict[str, Any]]:
    return [
        {
            "title": f"{topic}｜过来人整理",
            "likes": 1200 + index * 137,
            "comments": 80 + index * 11,
            "author": f"母婴博主{index}号",
        }
        for index, (topic, _) in enumerate(
            [
                (t, s)
                for t, s in [
                    ("新生儿睡眠倒退怎么破", 0),
                    ("一岁宝宝辅食黑名单", 0),
                    ("纸尿裤尺码对照表", 0),
                    ("宝宝湿疹护理避坑", 0),
                    ("待产包最全清单", 0),
                    ("婴儿抚触操教程", 0),
                    ("混合喂养怎么安排", 0),
                    ("宝宝爬行训练", 0),
                    ("母婴好物平价替代", 0),
                    ("断夜奶实战记录", 0),
                ]
            ]
        )
    ]


def _niche_opportunities() -> list[dict[str, Any]]:
    return [
        {
            "topic": topic,
            "potential_score": 0.7 + index * 0.05,
            "audience_match": "0-2岁新手妈妈",
            "entry_barrier": "低",
        }
        for index, topic in enumerate(["睡眠倒退期记录流", "辅食翻车合集", "平价纸尿裤横评"])
    ]


def _copy_body() -> str:
    sentences = [
        "凌晨三点的第无数次哄睡，我终于承认：睡眠倒退不是宝宝的问题，是我把期望调太高了。",
        "这篇不聊理论，只讲我验证过有效的一个动作：把白天最后一觉压缩到四十分钟以内。",
        "很多妈妈问我辅食怎么加，我的原则只有一条——一次只加一样，连吃三天看反应。",
        "湿疹那段时间我囤了七支药膏，最后发现真正起作用的是保湿霜按克抹，一天三次。",
        "待产包别照抄网红清单，产房真正用上的就那几样，其余的都是回家后慢慢补。",
        "纸尿裤不是越贵越好，尺码对、腰围贴好、四小时不漏，就是适合你宝宝的那款。",
        "夜奶不是必须断，妈妈自己扛得住就不断；扛不住的时候，方法比意志力有用。",
        "带娃没有标准答案，只有一个又一个可复现的小实验，欢迎把你的实验结果发在评论区。",
    ]
    return "".join(sentences)


def _note_body(seed: int) -> str:
    sentences = [
        "实操步骤拍成了图片版，评论区蹲一个反馈，我会把大家踩的坑汇总成第二篇。",
        "这篇写给我自己：三个月前连襁褓都包不好的我，现在可以单手换尿布了。",
        "数据都在图里，具体用到的链接我放在置顶评论，别买贵了。",
        "如果你也在同一阶段，先把收藏点起来，等娃睡着再慢慢看。",
    ]
    return sentences[seed % len(sentences)] + sentences[(seed + 1) % len(sentences)]


def _version_body(seed: int) -> str:
    heads = ["A 案：体验叙事流", "B 案：清单攻略流", "C 案：翻车反差流"]
    tail = [
        "开头三行先给结论，中间两段讲一个具体夜晚的完整操作，结尾留互动钩子。",
        "开头直接上清单图，每一条后面跟一句为什么，结尾补一个常见误区。",
        "开头讲失败现场，转折给修正动作，结尾用宝宝现在的小视频收束情绪。",
    ]
    return heads[seed % 3] + "：" + tail[seed % 3] + _copy_body()[:240]


def _trend_data() -> dict[str, Any]:
    return {
        "hot_topics": _hot_topics(),
        "trending_keywords": _keywords(),
        "competitor_posts": _competitors(),
        "niche_opportunities": _niche_opportunities(),
        "timestamp": "2026-09-14T09:30:00",
    }


def _content_plan() -> dict[str, Any]:
    return {
        "selected_topic": "新生儿睡眠倒退怎么破",
        "content_angle": "过来人实测记录流，不讲理论只讲可复现动作",
        "content_type": "experience_note",
        "target_audience": "0-1 岁宝宝的新手妈妈，正在经历睡眠倒退期",
        "key_points": ["压缩最后一觉", "固定睡前程序", "白天补觉上限", "妈妈情绪优先"],
        "suggested_timing": "工作日 21:30-22:30",
        "hashtags": ["#新生儿睡眠", "#睡眠倒退", "#新手妈妈", "#母婴实测", "#哄睡"],
        "urgency": "medium",
    }


def _copy_content() -> dict[str, Any]:
    return {
        "title_candidates": [
            "睡眠倒退第 7 天，我试对了这一个动作",
            "凌晨三点的哄睡，被我压缩到四十分钟",
            "别熬了，睡眠倒退期就吃这一套",
            "过来人实测：睡倒退不熬妈妈的方法",
            "夜醒五次到一次，中间我改了什么",
        ],
        "selected_title": "睡眠倒退第 7 天，我试对了这一个动作",
        "body_text": _copy_body(),
        "hashtags": ["#新生儿睡眠", "#睡眠倒退", "#新手妈妈", "#母婴实测", "#哄睡"],
        "cta": "评论区聊聊你家睡倒退持续了几天",
        "emoji_usage": ["🌙", "🍼", "✅"],
        "tone": "peer_support",
    }


def _visual_plan() -> dict[str, Any]:
    return {
        "cover_prompt": "暖色调实拍风格，妈妈抱宝宝坐在飘窗边，留出上方三分之一标题区",
        "image_count": 4,
        "image_prompts": [
            "凌晨三点手机屏幕亮度调到最低，妈妈单手抱娃的侧影",
            "睡眠记录 app 截图示意，夜醒次数从五次降到一次的趋势",
            "睡前程序四步图示：洗澡、抚触、喂奶、关灯",
            "宝宝睡熟后的俯拍，被子一角露出小手",
        ],
        "layout_style": "四宫格实拍 + 手写标注",
        "color_palette": ["奶白", "浅驼", "暖橘"],
        "font_suggestion": "圆体加粗标题 + 手写体标注",
        "brand_elements": ["账号角标", "系列期数角标"],
        "image_paths": [],
    }


def _ripple_prediction() -> dict[str, Any]:
    return {
        "estimated_reach": 18500,
        "estimated_interactions": 1420,
        "verdict": "值得一试",
        "confidence": 0.71,
        "key_influencers": [
            {
                "name": f"母婴博主{i}号",
                "platform": "xhs",
                "followers": 8000 + i * 900,
                "fit_score": round(0.6 + i * 0.03, 2),
            }
            for i in range(8)
        ],
        "spread_path": [
            {"step": i + 1, "node": f"母婴社群{i + 1}", "prob": round(0.85 - i * 0.09, 2)}
            for i in range(6)
        ],
        "phase_vector": {f"phase_{i}": round(0.1 + i * 0.08, 3) for i in range(10)},
        "relative_estimate": {
            "vs_account_median": 1.6,
            "vs_niche_median": 1.2,
            "upside": 2.3,
            "downside": 0.8,
        },
        "confidence_gate": {"pass": True, "threshold": 0.6, "observed": 0.71},
        "quality": {"sample_size": 42, "stale_days": 0, "source_count": 3},
    }


def _ripple_pmf() -> dict[str, Any]:
    return {
        "pmf_score": 0.68,
        "buckets": {f"{i * 10}-{i * 10 + 10}": round(0.02 * i + 0.01, 3) for i in range(12)},
        "drivers": ["选题命中率", "标题钩子强度", "发布时间匹配"],
        "drags": ["图面同质化", "话题饱和度"],
        "per_phase": {f"p{i}": round(0.05 + i * 0.07, 3) for i in range(9)},
        "history_fit": {"rank": 0.22, "sample": 35},
    }


def _blogger_candidates() -> list[dict[str, Any]]:
    return [
        {
            "blogger_id": f"blg{i:03d}",
            "name": f"母婴博主{i}号",
            "platform": "xhs",
            "followers": 8000 + i * 900,
            "avg_likes": 300 + i * 25,
            "tags": ["新生儿", "实测"],
            "match_score": round(0.55 + i * 0.06, 2),
        }
        for i in range(6)
    ]


def _blogger_notes() -> list[dict[str, Any]]:
    return [
        {
            "note_id": f"note{i:03d}",
            "title": f"睡眠倒退实测第 {i} 篇",
            "body": _note_body(i),
            "hashtags": ["#新生儿睡眠", "#实测"],
            "likes": 900 + i * 210,
            "collects": 400 + i * 95,
            "comments": 60 + i * 13,
            "engagement_rate": round(0.04 + i * 0.004, 3),
            "cover_url": f"https://img/x{i}.jpg",
        }
        for i in range(5)
    ]


def _content_versions() -> list[dict[str, Any]]:
    return [
        {
            "version_id": f"v{i + 1}",
            "title": f"睡眠倒退第 7 天（{i + 1} 版）",
            "body": _version_body(i),
            "hashtags": ["#新生儿睡眠", "#实测"],
            "image_prompts": ["睡前四步图", "夜醒趋势图", "俯拍收尾图"],
            "style_suggestion": ["体验叙事", "清单攻略", "翻车反差"][i],
            "changes_summary": f"第 {i + 1} 版调整开头钩子与结尾互动",
            "predicted_score": round(0.62 + i * 0.05, 2),
        }
        for i in range(3)
    ]


def _optimization_analysis() -> dict[str, Any]:
    return {
        "gaps": ["开头三行没有给结论", "缺一张趋势截图佐证", "话题标签太泛", "结尾互动钩子弱"],
        "suggestions": ["首行直接给动作", "补夜醒趋势图", "缩到三个精准标签", "提问式收尾"],
        "viral_patterns": ["凌晨时间线叙事", "次数对比数字", "单动作可复制"],
    }


def _viral_posts() -> list[dict[str, Any]]:
    return [
        {
            "post_id": f"vp{i:03d}",
            "title": f"同类选题爆款拆解 {i + 1}",
            "body": _note_body(i) + "（爆款正文摘录，用于对标分析）",
            "hashtags": ["#母婴", "#爆款拆解"],
            "author": f"母婴博主{i}号",
            "likes": 5000 + i * 800,
            "collects": 2000 + i * 300,
            "comments": 300 + i * 40,
            "image_urls": [f"https://img/vp{i}.jpg"],
            "posted_at": f"2026-09-{i + 1:02d}T21:00:00",
            "topic": "新生儿睡眠",
            "engagement_rate": round(0.05 + i * 0.003, 3),
            "collected_at": FIXED_TS,
        }
        for i in range(10)
    ]


def _engagement_actions() -> list[dict[str, Any]]:
    return [
        {
            "action_type": "reply",
            "target_id": f"comment{i:03d}",
            "content": "谢谢反馈，第二篇已按你说的补充了趋势图",
            "timestamp": FIXED_TS,
        }
        for i in range(4)
    ]


# ── superstep sequence (trend mode long task) ───────────────────────────────

STEPS: list[tuple[str, dict[str, Any]]] = [
    ("create_thread", {}),
    ("trend_scout", {"trend_data": _trend_data()}),
    ("content_strategist", {"content_plan": _content_plan()}),
    ("copywriter", {"copy_content": _copy_content()}),
    ("visual_designer", {"visual_plan": _visual_plan()}),
    (
        "review_gate",
        {
            "human_feedback": {
                "decision": "approved",
                "comments": "结论前置，补趋势图",
                "revisions": ["开头给结论"],
                "reviewer": "jamery",
            }
        },
    ),
    (
        "publisher",
        {
            "publish_result": {
                "post_id": "post-muying-001",
                "post_url": "https://xhs/abc",
                "published_at": FIXED_TS,
                "ab_variant": None,
                "status": "published",
                "workflow_thread_id": _THREAD,
                "platform_post_id": "65f0e1",
                "link_status": "linked",
            }
        },
    ),
    (
        "analyst",
        {
            "analytics": {
                "post_id": "post-muying-001",
                "views": 8600,
                "likes": 640,
                "collects": 980,
                "comments": 152,
                "shares": 88,
                "engagement_rate": 0.216,
                "reach_rate": 0.61,
                "timestamp": FIXED_TS,
                "insights": ["收藏率高于同类均值"],
                "recommendations": ["七天后发续集"],
            }
        },
    ),
    ("ripple_analyzer", {"ripple_prediction": _ripple_prediction(), "ripple_pmf": _ripple_pmf()}),
    (
        "blogger_research",
        {
            "blogger_candidates": _blogger_candidates(),
            "selected_blogger": {
                "blogger_id": "blg003",
                "name": "母婴博主3号",
                "platform": "xhs",
                "followers": 10700,
                "avg_likes": 375,
                "tags": ["新生儿", "实测"],
                "match_score": 0.73,
            },
        },
    ),
    ("blogger_notes_fetch", {"blogger_notes": _blogger_notes()}),
    (
        "draft_generator",
        {
            "draft_content": {
                "text": _version_body(0),
                "images": ["img1", "img2"],
                "title": "睡眠倒退第 7 天（草稿）",
                "hashtags": ["#新生儿睡眠"],
                "provided_at": FIXED_TS,
            }
        },
    ),
    (
        "version_writer",
        {
            "content_versions": _content_versions(),
            "optimization_analysis": _optimization_analysis(),
        },
    ),
    ("viral_collector", {"viral_posts": _viral_posts()}),
    ("engagement_runner", {"engagement_actions": _engagement_actions()}),
]

_LLM_STEPS = {3, 4, 8, 11, 12}


def _control() -> dict[str, Any]:
    return {
        "phase": "completed",
        "prev_phase": "analyzing",
        "current_agent": "engagement_runner",
        "error": None,
        "error_class": None,
        "pause_reason": None,
        "retry_count": 0,
        "execution_mode": "single",
        "workflow_mode": "trend",
        "account_id": "acc-muying",
        "session_id": "sess-muying",
        "thread_id": _THREAD,
        "created_at": FIXED_TS,
        "updated_at": FIXED_TS,
        "niche": "母婴",
        "topic": "新生儿睡眠倒退怎么破",
        "publish_options": {"dry_run": False, "auto_publish": True},
        "dry_run": False,
        "auto_publish": True,
    }


def _perf_log_after(step_index: int) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for index in range(1, step_index + 1):
        node, _ = STEPS[index]
        entry: dict[str, Any] = {
            "agent": node,
            "started_at": f"2026-09-14T09:{index * 4:02d}:00",
            "completed_at": f"2026-09-14T09:{index * 4 + 3:02d}:30",
            "duration_seconds": 3.5,
            "status": "success",
        }
        if index >= 2:
            entry["kind"] = "llm" if index in _LLM_STEPS else "node"
        entries.append(entry)
    return entries


def _inline_after(step_index: int) -> dict[str, Any]:
    values: dict[str, Any] = dict(_control())
    for _, delta in STEPS[: step_index + 1]:
        values.update(delta)
    return values


def _post_shape(values: dict[str, Any]) -> dict[str, Any]:
    out = dict(values)
    artifacts: dict[str, Any] = {}
    for key in sorted(REFABLE_FIELDS):
        body = out.pop(key, None)
        if not body:
            continue
        artifacts[key] = make_ref(key, "latest", body, updated_at=FIXED_TS)
        if key == "content_versions":
            out["versions_meta"] = versions_meta_of(body)
        elif key == "blogger_notes":
            out["blogger_notes_meta"] = blogger_notes_meta_of(body)
        elif key == "trend_data":
            out["trend_summary"] = trend_summary_of(body)
    if artifacts:
        out["artifacts"] = artifacts
    return out


def _state_after(step_index: int, shape: str) -> dict[str, Any]:
    inline = _inline_after(step_index)
    if shape == "pre":
        # Pre-P1a reality check: both dead keys were initialised to [] at
        # thread creation and never written; the inline telemetry list was the
        # only unbounded rider.
        inline["messages"] = []
        inline["content_history"] = []
        inline["performance_log"] = _perf_log_after(step_index)
        return inline
    return _post_shape(inline)


def _artifact_store_bytes() -> int:
    """Final Artifact Store footprint: one latest body per written kind."""
    total = 0
    for _, delta in STEPS:
        for key, body in delta.items():
            if key in REFABLE_FIELDS and body:
                encoded = json.dumps(
                    body, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
                ).encode("utf-8")
                total += len(encoded)
    return total


def main() -> None:
    serde = JsonPlusSerializer()
    rows = []
    for index, (node, delta) in enumerate(STEPS):
        pre = len(serde.dumps_typed(_state_after(index, "pre"))[1])
        post = len(serde.dumps_typed(_state_after(index, "post"))[1])
        big = [key for key in delta if key in REFABLE_FIELDS]
        note = "ref: " + ",".join(sorted(big)) if big else "inline both shapes"
        rows.append((index, node, pre, post, note))

    pre_final = rows[-1][2]
    post_final = rows[-1][3]
    pre_total = sum(row[2] for row in rows)
    post_total = sum(row[3] for row in rows)
    store_bytes = _artifact_store_bytes()

    print("# Checkpoint size benchmark — 母婴长任务 (P1a pre vs post)\n")
    print(
        f"- langgraph {version('langgraph')} / langgraph-checkpoint "
        f"{version('langgraph-checkpoint')}; serde: msgpack + JsonPlusSerializer"
    )
    print(f"- {len(rows)} supersteps, full-snapshot semantics, no pruning\n")
    print("| # | node (write) | pre bytes | post bytes | reduction | note |")
    print("|---|---|---:|---:|---:|---|")
    for index, node, pre, post, note in rows:
        cut = f"{100 * (1 - post / pre):.0f}%" if pre else "n/a"
        print(f"| {index} | {node} | {pre} | {post} | {cut} | {note} |")
    print("")
    print(
        f"- final superstep: pre {pre_final} B vs post {post_final} B "
        f"({100 * (1 - post_final / pre_final):.1f}% smaller)"
    )
    print(
        f"- cumulative (write amplification over the task): pre {pre_total} B vs "
        f"post {post_total} B ({100 * (1 - post_total / pre_total):.1f}% smaller)"
    )
    print(
        f"- artifact store footprint (bodies moved, not vanished): {store_bytes} B "
        f"written once each, never re-serialized by checkpoints"
    )
    print(
        f"- net persisted bytes (checkpoints + store): pre {pre_total} B vs "
        f"post {post_total + store_bytes} B "
        f"({100 * (1 - (post_total + store_bytes) / pre_total):.1f}% smaller)"
    )


if __name__ == "__main__":
    main()
