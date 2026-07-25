# creator-stats-incremental-sync

## 背景

创作者数据同步（CDP 爬取）每次全量访问每篇笔记的详情页与公开正文页，请求密集且无间隔，易被小红书风控判定为违规；批量多账号连续爬取进一步放大风险。

## 目标

1. 只同步当前激活账号（`get_active_account`）：切换账号后旧账号立即停止同步。
2. 增量同步：仅对新笔记、近 7 天发布、或列表指标有变化的笔记访问详情页；正文只补缺失（已有正文永不重抓，回看 30 天）。
3. 请求抖动：逐篇访问间随机 2–6s；调度周期 ±10% 抖动。
4. 风控熔断：详情/正文访问连续 3 次异常即停止；正文连续 5 次空结果（疑风控 shell 页）即停止。
5. 全部阈值可通过环境变量调整（见 docs/configuration.md）。

## 验证

- `pytest tests/unit` 全绿（含新增 test_incremental_sync.py 与 test_cdp_transport.py 增量用例）
- `ruff check` + `ruff format --check` + `mypy` 通过
