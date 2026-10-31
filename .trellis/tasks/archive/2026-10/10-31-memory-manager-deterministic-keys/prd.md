# MemoryManager 写入确定性 key（票 5aj）

## Goal

关闭 promotion 父 PRD §10 登记项：`MemoryManager.store_insight` / `store_audience_preference` / `store_strategy_note` 不再 `key=uuid4()`，改为由内容派生的确定性 key，使同一结论可按键 upsert/去重（对齐 Slice C `candidate_id_for` 思路）。`store_content_record` 已用 `post_id`，不动。

## What I already know

* 三方法今日 `str(uuid.uuid4())` → 同文多次写入并存多行，无法按键 supersede
* `candidate_id_for(ns, source_ref)` = `cand_` + sha256[:16]（`promotion.py`）
* 召回走 `asearch` + keyword，不依赖 uuid；改 key 不破读路径
* 历史 uuid 行：本票**不做迁移扫表**；新旧可并存，语义检索仍可见

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| Key 公式 | `mem_{sha256(f"{kind}\\x1f{text.strip()}").hexdigest()[:16]}`；kind ∈ `insight` / `preference` / `strategy_note` |
| 空 text | `ValueError`（非法输入，与 promotion SourceCheck 同族） |
| metadata | 仍写入 value；**不**进 key（同 insight 不同 metadata → 覆盖为最新 value） |
| 旧 uuid 行 | 不迁移；文档诚实边界 |
| content_history | 已用 post_id；out of scope |

## Requirements

1. 新增 `memory_record_key(kind, text) -> str`（可测纯函数，放 `store.py`）
2. 三 store_* 改用该 key
3. 单测：同 text 两次 aput 同 key；不同 text 不同 key；空 text raises
4. 划掉 §10 uuid4 项；docs/memory-promotion 或 agent-os 注记

## Acceptance Criteria

* [x] 三写入方法使用确定性 key，不再 uuid4
* [x] 同内容重复写入落到同一 key
* [x] 空文本拒绝；旧行不迁移已文档化
* [x] 测试绿；§10 项关闭

## Out of Scope

* 历史 uuid 行迁移 / 合并
* 平台 publish 对账查询（5ai 后续刀）
* CreativeMemory keys

## Technical Notes

* `backend/memory/store.py`；`tests/unit/memory/test_store.py`
* 对齐 `candidate_id_for` 的 sha256 + 短 hex 前缀风格
