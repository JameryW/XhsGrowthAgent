# P1a 技术方案：Agent Kernel 最小骨架 + State 三层拆分（评估件）

> **决策已定（2026-09-13 用户拍板）**：D1=一刀切+旧线程透传；D2=BaseStore + ArtifactStore façade；D3=workflow_events 表+内存回退（按推荐）；D4=/status 保全文响应（hydration 收口，前端零改动）；D5=对象范围收敛到 3+2 件（RunContext→P1b、Task/ToolResult→P1c、Action 通用化→P2a，父 prd 已同步修订）。下文选项描述保留作代价记录。

依据：research/state-consumer-map.md、research/persistence-inventory.md。目标：LangGraph checkpoint 只留 RuntimeState；大块业务内容进 Artifact Store（按引用）；telemetry 进 Event/Trace Store。**本阶段不动 HTTP 契约、不引入未承重抽象。**

## 一、目标模型与字段归置

```
┌ RuntimeState（checkpoint，每 superstep 序列化，必须小且有界）
│   phase/current_agent/error/error_class/pause_reason/retry_count/…
│   counts+flags: versions_meta、trend_summary、blogger_notes_count、brief_meta
│   refs:  {"copy": "artifact://copy/<id>", "visual": …, "draft": …}
│   路由谓词只允许消费本层字段
├ Artifact Store（LangGraph BaseStore, ns=("artifacts",thread_id,kind)）
│   copy/visual/plan/brief_text/viral_posts/versions bodies/draft/analytics/…
└ Event/Trace Store（新 workflow_events 表 + 内存回退）
    llm cost/timing、tool、error、human_wait、action → /status 的 agent_timeline 唯一来源
```

**归置表（摘要，全量见勘察 A 字段表）**：直接删除=messages、state.content_history（死字段）；→Event Store=performance_log；→Artifact（一跳/终末，Diff 1-2）=viral_posts、user_viral_links、shooting_plan、optimization_analysis、ripple_comparison、analytics、copy_content、visual_plan、draft_content；**摘要化**（路由/UI 需长度/真值/列表）=content_versions（→versions_meta）、trend_data（→trend_summary）、blogger_notes、brief_content（raw_text 外置、meta 留驻）、ripple_prediction/pmf（大向量外置、verdict 留驻）；**留守**=evaluation_result、publish_result、phase 族、retry/cycle/revision 计数、publish_options/dry_run。

## 二、决策点（选项 / 代价 / 推荐）

### D1 旧线程迁移策略
- **A（推荐·一刀切）**：新 run 用新 schema；**不重写存量 checkpoint**。旧线程（legacy 全量 blob）由 hydration 层识别后**原样透传**渲染；新线程按 refs 水合。部署=排空窗（停止 start，在途线程跑完或标 stale）；回滚代价：新 schema 在途线程需先停（旧代码无 artifact 解析），回滚前需 drain，作为连带约束接受。
- B：脚本改写存量 checkpoint（解 msgpack→拆分→回写）。复杂度/风险高（无 GC 经验、序列化内部格式），不推荐。
- C：双写观察期。拒绝（历史偏好：拒绝双写）。

### D2 Artifact 后端
- **A（推荐）**：复用 LangGraph BaseStore（dev InMemory/Sqlite 生态、prod AsyncPostgresStore 现成），`ArtifactStore` 薄 façade（put/get/delete；value=类型化 dict + content_hash）；store 已是节点注入通路。代价：无 SQL 级查询/清理（可后续 façade 内换后端）；dev InMemory 重启丢（与现 checkpoint dev 行为一致）。
- B：专用 PG 表 + is_pool_ready 双后端（creator_agent 模式）。查询/GC 更强，但新增第三套存储栈与迁移面。
- C：文件系统 + path refs。图片现状已是路径（维持），但文本正文入库不入盘，避免备份/部署一致性问题。

### D3 Event Store
- **A（推荐）**：新 `workflow_events(thread_id, seq, ts, kind, payload)` 表 + 内存回退（复制 creator_agent 双后端先例）；performance_log 从 checkpoint 删除（新 run），agent_timeline/quality-trend 读取源切换；一刀切无双写。
- B：events 也进 BaseStore——无有序分页，弃。

### D4 HTTP/前端契约
- **A（推荐，本阶段）**：/status 响应经 hydration 层**继续返回全文聚合视图**（前端零改动；30 键硬编码收口到唯一模块）；checkpoint 瘦身不改变线上 payload。按需拉取（slim refs + artifact API）留待 P1b/UI 演进任务。
- B：slim 响应 + 新增 GET artifact API——前后端同改、发布耦合，收益（轮询字节）非本阶段目标。

### D5 核心对象范围（对父任务 prd 的修订建议）
- **A（推荐）**：本任务只落 **ArtifactRef + ArtifactStore + EventStore + RuntimeState 字段矩阵 + hydration 层** 五件；RunContext 随 P1b（Context Compiler 的第一消费方）引入；Task/ToolResult 归 P1c；ActionIntent/Receipt 通用化归 P2a（现仅 creator_agent 使用，避免半成品抽象——同 P0 选 ContextVar 不选 RunContext 的理由）。
- B：按原 prd 一次定义六对象——六个里三个无消费方，死代码风险。

## 三、实施切片（任务内小步提交，每步全绿）

1. **S1 纯减法**：删 messages/state.content_history 及 6 个读面残留；hydration 模块雏形收口 /status、/history、recover、showcase、realtime、history-file 键枚举。
2. **S2 Event 外置**：performance_log→workflow_events；agent_timeline 换源；P0 的 ContextVar drain 落点改为事件写通道。
3. **S3 Artifact 主体**：ArtifactStore façade + Diff1-2 字段 refs 化 + content_versions→versions_meta + **架构测试**（路由函数对 ref'd state 与全量 state 结果恒等；versions_meta 保持全序且 id 稳定——吸取 free-draft 排序承重教训）。
4. **S4 硬骨头**：brief_content/trend_data/ripple 摘要化；publish 的 content_hash 计算源改自 artifact（锚定 P0 幂等语义不变）；legacy 线程 hydration fixture 测试。

## 四、风险与未决问题

- **路由承重**：content_versions/trend_data/blogger_notes 被路由读长度/真值——摘要字段一旦漂移即行为漂移；靠架构测试兜。
- **P0 契约连带**：pause_reason/human_decision 依赖 evaluation_result（留守，无险）；publish_id 内容哈希源变化需等价性测试。
- **前端按下标定位**（项目记忆）：任何列表外置+回注必须保持全序与既有 tie-break。
- 双后端：dev(SQLite/InMemory) 与 prod(PG) 行为差是存量问题；本任务把差异收口进 façade，不扩大。
- 未决：checkpoint 无 GC 是否顺手加"completed 线程 N 天后裁剪 runtime 快照"？（建议单列小任务，不混入 P1a）

## 五、验收

checkpoint 单 superstep 序列化体积显著下降（基准：母婴长任务前后对比脚本）；全量测试+CI 六门绿；旧线程 /status、/history、recover、showcase 回归不劣化；无新增双写。
