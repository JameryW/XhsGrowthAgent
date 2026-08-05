# 删除 xhs_signature.py 死 method

## 背景

`backend/services/xhs_signature.py` 含 3 类：`XHSSignature`（签名）、`XHSAntiSpider`（反爬）、`XHSCookieParser`（cookie 解析）。
仅 `xhs_client.py` 消费此模块（codegraph 报 creator_stats/client + ripple_late_recheck 是误报，grep 0 匹配）。

## 死代码清单（0 prod 消费，grep 确认）

### XHSSignature
- `generate_sign` — 仅 `add_sign_to_params` 调，后者 0 消费 → 间接死
- `add_sign_to_params` — 0 消费

### XHSAntiSpider（整类删除）
- `get_fingerprint` — 0 消费
- `_generate_device_id` — 仅 get_fingerprint 用
- `get_web_id` — 0 消费

### XHSCookieParser
- `get_user_id` — 0 消费

## 保留（活代码）

- `XHSSignature.generate_x_s` / `generate_x_t` / `add_sign_to_headers` — xhs_client._request 用
- `XHSCookieParser.extract_from_string` — is_valid 内部用
- `XHSCookieParser.is_valid` — xhs_client:296 用

## AC

1. 删 6 死 method + XHSAntiSpider 整类
2. `ruff check .` + `mypy backend` + `pytest` 全绿
3. xhs_client.py 不受影响（add_sign_to_headers / is_valid 保留）

## 风险

低。纯签名工具 helper，0 prod 消费。XHSAntiSpider 是反爬占位但从未接入 → YAGNI 删。
