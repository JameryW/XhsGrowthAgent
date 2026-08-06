# 删除 ripple integration 死代码 wrapper + service.recover_result

## 背景

`backend/tools/ripple/integration.py` 是旧 API 层，部分 function 被 `client.py` 的 `ripple_*` tool 替代。
仍活的 wrapper：`predict_spread`, `validate_pmf`, `get_report`（agent 直接 import + 调用）。
死的 wrapper：0 prod 消费，仅测试覆盖。

`RippleService.recover_result` method 设计给"未来后台轮询扩展"（docstring 原文），但 PR#466 的
`ripple_late_recheck` 节点用自己的 bounded poll 逻辑实现晚到结果恢复，从未调 `recover_result`。
`RecoveryStatus` model 仅 `recover_result` 用。

## 死代码清单（0 prod 消费，已 grep + codegraph 双重确认）

### integration.py function
- `get_result` (:142) — 0 prod
- `cancel_simulation` (:162) — 0 prod（agent 调 `service.cancel_simulation()` method 绕过 wrapper）
- `recover_result` (:181) — 0 prod
- `parse_spread_prediction` (:201) — 0 prod（`service._parse_spread_result` 活，wrapper 0）
- `parse_pmf_result` (:213) — 0 prod（`service._parse_pmf_result` 活，wrapper 0）
- `_parser_service` (:26) — 仅 `parse_*` wrapper 用，随 wrapper 删

### ripple_service.py
- `RecoveryStatus` class (:36) — 仅 `recover_result` 用
- `recover_result` method (:1100) — 0 prod 消费（late_recheck 节点不调）

### test_ripple.py 测试函数
- `test_parse_spread_prediction_success` / `_current_ripple_shape` / `_error` (3)
- `test_parse_pmf_result_success` / `_current_ripple_shape` / `_error` (3)
- `test_cancel_simulation_wrapper` / `_handles_failure` (2)
- `test_recover_result_wrapper` / `_handles_failure` (2)

## 保留（活代码，勿删）

- `predict_spread`, `validate_pmf` (integration.py) — content_strategist 直接 import
- `get_report` (integration.py) — analyst 直接 import
- `_get_service` (integration.py) — 上述活 wrapper 用
- `RippleService.get_result` method — `submit_and_wait` 内部调
- `RippleService.cancel_simulation` method — analyst/content_strategist 调
- `RippleService._parse_spread_result` / `_parse_pmf_result` method — workflow.py + service 内部调
- `ripple_cancel_simulation` / `ripple_get_simulation_result` 等 (client.py) — agent tool

## AC

1. integration.py 6 个死 function 删除，活 function 保留
2. ripple_service.py `RecoveryStatus` + `recover_result` 删除
3. test_ripple.py 10 个对应测试删除，剩余测试全绿
4. `ruff check .` + `mypy backend` + `pytest` 全绿
5. integration.py 仍可 import（predict_spread/validate_pmf/get_report 活）
6. client.py 不受影响

## 风险

低。0 prod 消费，纯机械删除。`recover_result` 是"未来扩展"占位（docstring 自述），YAGNI 删。
若未来需后台轮询恢复，late_recheck 节点模式已验证可行，重写即可。
