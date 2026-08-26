# Free drafts anchor material vault calibration（素材锚定激活校准）

## Goal

创作记忆三层中 Style/Play 校准已随 08-25-free-style-anchors 打通，但素材层（Material
Vault）的 effectiveness 全系统休眠：`build_calibration_payload` 读取
`copy_content.used_material_ids` + `material_effectiveness`，而 analyst 从不填后者，
`_calibrate_materials` 因此永远空转；且 creative context 素材区不暴露 id，智能体无从
锚定。本轮让自由草稿可选携带 `material_ids`，发布后随同 style/play 一并校准。

## Research

- `build_calibration_payload`（calibrator.py:79）已读 `copy_content.used_material_ids`
  与 `copy_content.material_effectiveness`；后者为空时 `_calibrate_materials` 直接
  return 0 —— 素材更新依赖该映射。
- analyst.py 无 material_effectiveness 计算（grep 无匹配）→ 合成逻辑放 builder 内、
  仅在"有 ids 但映射为空"时兜底，工作流同样受益且不改变现有行为。
- 阈值常量：`EFFECTIVENESS_THRESHOLD = 0.3`、`DOWNGRADE_FACTOR = 0.8`
  （creative.py:35-36）。效果值合成规则与 play_success 对齐：
  engagement ≥3% → 0.9，否则 0.25（低于阈值 → weight×0.8 软降级）。
- creative context 素材区（creative.py:650-656）无 id= 前缀 → 补齐与风格/打法一致的
  锚定入口。

## Requirements

1. `backend/api/routes/free.py`：
   - `FreeDraft` / `FreeDraftUpdate` 加可选 `material_ids: list[str]`（default 空）；
   - `_to_copy_content` 输出 `used_material_ids`。
2. `backend/memory/calibrator.py`：`build_calibration_payload` 在 ids 非空且映射为空时
   按 play_success 规则合成 `{mid: 0.9 | 0.25}`；显式传入的映射优先。
3. `backend/memory/creative.py`：素材行加 `id={mid} `（沿用风格/打法的格式）。
4. `backend/services/omp_bridge.py`：工具 schema 增 `material_ids` 数组参数 +
   usage 文本同步。
5. spec free-creation.md：字段表、create/analytics 行为、校准触发条件补素材链。

## Acceptance criteria

1. create/PATCH 持久化 material_ids；发布状态 copy_content.used_material_ids 正确。
2. analytics 有素材锚点+views>0 → payload 含 material_ids 与合成的
   material_effectiveness（≥3%→0.9）；显式映射不被覆盖。
3. 素材 context 行含 id=；omp schema 可传数组。
4. focused 测试绿 + ruff 干净。

## Out of scope

- 定时自动采集（CDP 常开依赖 + 反风控调度哲学冲突，继续留档）。
- GUI/TUI 锚点展示。
