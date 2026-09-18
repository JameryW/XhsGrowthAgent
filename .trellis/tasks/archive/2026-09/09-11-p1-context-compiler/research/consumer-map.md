# Context 拼装路径勘察（consumer-map，2026-09-14）

P1b S1 勘察件：全部 prompt 拼装点、替换 token、recall 调用矩阵、隐式默认清单。
行号基于 518d0dab。目标：S4 迁移按此图逐点销号。

## 一、拼装点总表（`_build_system_prompt` 调用面）

| agent:line | extra_context 来源 | 特殊 token | 备注 |
|---|---|---|---|
| base.py:156（通用实现） | 调用方传入 → `{memory_context}` | account_niche, memory_context | 11 个 agent 的公共路径 |
| analyst.py:92 | 无（空） | — | 纯模板 |
| brief_analyzer.py:60 | creative_ctx | — | |
| brief_analyzer.py:142 | 无 | — | |
| content_strategist.py:78 / 104 | memory_context | ripple_context 清空（79/105） | 主路径+变体 |
| content_strategist.py:136 / 299 | memory_context（retry 变体） | ripple_context 清空/填充（142/301） | retry 双形态 |
| content_analyzer.py:48 | 无 | — | |
| copywriter.py:104 | memory_context | ripple_context 填充（108） | |
| evaluator.py:130/224（**override**） | audience_ctx | weights_block / pass_threshold / reject_threshold（158-161）+ account_niche/memory_context | 自有实现，不走 base |
| viral_matcher.py:60 | 无 | — | |
| version_generator.py:80 / 229 | 无 | — | |
| shooting_planner.py:50 | 无 | — | |
| trend_scout.py:179 | memory_context + data_context **自拼**（见 §三） | — | 最野路径 |
| visual_designer.py:45 | creative_ctx | — | |

共 **15 个调用点 / 11 个 agent 文件**；agent `execute()` 调用点 13 处（base.py 注释口径）。

## 二、替换 token 清单（S3 分段 schema 的迁移对象）

| token | 出现点 | L 层归属（目标） |
|---|---|---|
| `{account_niche}` | base:159, evaluator:154 | L2 |
| `{memory_context}` | base:160, evaluator:155 | L4 |
| `{ripple_context}` | content_strategist:79/105/142/301, copywriter:108 | L5 |
| `{weights_block}` / `{pass_threshold}` / `{reject_threshold}` | evaluator:158-160 | L5 |
| user_msg 手拼 | trend_scout:183-187（账号定位/关注领域/输出要求） | L2+L3 |

prompt 来源：`backend/config/prompts/*.yaml`（system + user_template 两键，base.py:141-154）；
分段化后扩为 `system` 分段（L0 policy 段 + 占位标记）+ user_template（L3）。

## 三、trend_scout 自拼路径（最野，S4 首迁）

- L4 段：`_recall_memory(performance_insights, limit=3)` → "历史趋势洞察"列表串
  （134-138）。
- L5 段：`_fetch_real_data` 实时数据块（热门话题/关键词监控/竞品分析，140-172）；
  **降级路径 175-177：无实时数据 → 写死字符串"小红书实时数据不可用，基于你的知识生成
  趋势分析"**（现状靠字符串 magic value `data_source="llm_generated"` 区分——P1b 换
  RetrievalResult.mode 后此信息进事件面）。
- 拼接后整体塞 `extra_context`（179-181），user_msg 另手拼（183-187）。

## 四、recall 调用矩阵（`_recall_memory`，base.py:163-192）

| 调用点 | namespace | limit | 降级现状 |
|---|---|---|---|
| analyst.py:82 | content_history | 5 | 异常→warning+[] |
| copywriter.py:56 | content_history | 5 | 同上 |
| copywriter.py:63 | audience_preferences | 5 | 同上 |
| content_strategist.py:48 | performance_insights | 5 | 同上 |
| evaluator.py:212 | audience_preferences | 5 | 同上 |
| trend_scout.py:125 | performance_insights | **3** | 同上 |

- 全部单 namespace、独立调用（仅 trend_scout 与 _fetch_real_data gather 并行）。
- **strategy_notes namespace 已注册（base.py:178）但零 agent 调用**——dead ns，S2 定夺。
- 4 个 ns_map 键 fail-fast（P0-W2），但**异常静默降级未消**（§十五）——S2 根治点。

## 五、隐式默认清单（`niche = state.get("niche", "母婴")`，11 处）

base.py:158、analyst.py:98、blogger_scout.py:33/83、content_strategist.py:39、
copywriter.py:117、evaluator.py:151、blogger_gate.py:145、trend_scout.py:109、
visual_designer.py:47、review_gate.py:55（review_gate 为默认值字面量在常量表）。
D2' 拍板后全部删除，start 入口校验必填。

## 六、迁移销号顺序（S4 执行清单）

1. trend_scout（自拼 + 降级字符串 + 手拼 user_msg）
2. copywriter（双 ns recall + ripple_context）
3. content_strategist（4 个拼装点 + retry 双形态）
4. evaluator（override 实现 + weights 特例）
5. analyst / brief_analyzer / visual_designer（creative_ctx 类）
6. content_analyzer / viral_matcher / version_generator / shooting_planner（纯模板批）
7. base 通用路径收口 + blogger_gate/review_gate 默认值清除 + niche fail-fast 统一切换
