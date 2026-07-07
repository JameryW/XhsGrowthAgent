# 根因：copywriter style 变体静默失败 → 跳过第一层风格选择

## 现象
工作流 `xhs_c056e160...8bd617c1`：选完博主（mock_fallback_003，blogger_notes=3 篇）后，
直接到 choice_gate 第二层（A/B/C 版本对比，version_id=A/B/C，有 predicted_score，无 style_name），
**从未显示第一层 StyleCompare 风格选择页**。style_selected=None。

## 设计流程（graph/routers.py + choice_gate.py 两层 choice_gate）
```
copywriter → content_analyzer_router:
  - content_versions > 1 (style 变体 style_a/b/c，带 style_name) → choice_gate 第一层（选风格）
  - content_versions 空 → version_generator（生成 A/B/C）
version_generator → should_present_choice:
  - versions > 1 → choice_gate 第二层（选 A/B/C）
choice_gate → choice_outcome:
  - style_selected=True（刚选完风格）→ version_generator 生成 A/B/C
  - style_selected=False（刚选完 A/B/C）→ visual_designer
```

## 触发条件
copywriter `_generate_style_variants`（backend/agents/copywriter.py:185-268）**只在
`blogger_notes` 非空时调用**（copywriter.py:130-134）。该工作流 blogger_notes=3，**应该**
生成 style 变体。

## 根因（静默失败）
`_generate_style_variants` 调 LLM 生成 variants（line 247-258），用
`_parse_json_response` 解析（line 260），取 `parsed.get("variants", [])`（line 261）。

若 LLM 返回的 JSON：
- 解析失败（_parse_json_response 失败返回 {}）→ variants=[]
- 无 `variants` key → variants=[]
- variants 为空数组 → variants=[]

则 `_generate_style_variants` **直接 return []**（line 268），**无任何日志/告警/重试**。

copywriter.py:181 `if content_versions:` 空则不写 content_versions → state.content_versions
保持空 → `content_analyzer_router`（routers.py:195 `versions = state.get("content_versions", [])`，
len==0 不 >1）→ 走 `version_generator` → 生成 A/B/C → choice_gate 第二层。

用户因此看不到 StyleCompare（前端 OptimizationPanel.vue:39-41 `isStyleChoice` 判
`content_versions[0]?.style_name`，A/B/C 无 style_name → 显 VersionCompare）。

## 证据链
- state: blogger_notes=3（非空，应触发 style 生成）
- state: content_versions 是 A/B/C（version_id=A/B/C，有 predicted_score，无 style_name）
- state: current_agent=version_generator（说明走了 version_generator，即 copywriter 没出 content_versions）
- state: style_selected=None（第一层从未发生）
- _generate_style_variants 无失败日志/重试（line 260-268）

## 修复方向
`_generate_style_variants` 解析失败/空 variants 时：
1. 记 warning 日志（含 LLM 原始响应片段，便于诊断）
2. 重试一次（LLM 格式错误常偶发，重试可救）
3. 仍失败则记 error + 返回空（保持现有降级，不阻塞流程，但要有日志）

不做：不强制要求 style 变体（那会阻塞流程）；不改路由（降级行为本身合理——
无 style 变体时走 A/B/C 是可接受的 fallback，问题是静默无日志难诊断）。

## 范围
仅 copywriter.py 的 `_generate_style_variants`。不动 graph 路由、不动 choice_gate、
不动前端。前端 StyleCompare / 两层 choice_gate 设计本身正确，缺的是 style 变体可靠生成。
