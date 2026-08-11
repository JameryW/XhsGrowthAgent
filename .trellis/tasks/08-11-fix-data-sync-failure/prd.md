# Creator Stats 数据同步失败修复

## 目标

让真实 Creator Center 同步在部署后的常驻 Chrome/CDP 环境中快速失败、正确捕获页面响应，并确保数据库启动降级不会把一个失效的 Postgres 连接误当成可用持久化后端。

## 调查证据

- 生产验收记录显示 Postgres 与账号 CDP 端口探测正常，但调度器尚未完成首轮，当前还不能把健康检查告警当作一次成功或失败的同步结果。
- `CdpTransport` 当前用完整路径字符串匹配响应，只识别 `page` 查询参数；尾斜杠或 Creator Center 使用 `page_num` 时，响应会被忽略或分页状态不会前进，最终可能超时或只导入第一页。
- `CdpTransport._ensure_browser` 没有把自身的超时传给 `connect_over_cdp`，CDP 握手异常时可能长时间占住一次同步请求。
- CDP 握手异常后的 Playwright 清理也可能卡在 `stop()`，会掩盖原始连接错误并让请求迟迟不返回。
- FastAPI lifespan 在 Postgres 初始化失败后切换到 SQLite graph，但没有关闭已创建的 app-level Postgres pool；后续 `is_pool_ready()` 仍可能为真，调度器会进入一个混合且不可用的同步状态。

## 实施范围

1. 规范化 Creator Center 响应路径，兼容尾斜杠；分页索引兼容 `page`、`page_num` 和 `pageNo`，不改变现有 0/1 起始页语义。
2. 将 Creator Stats 的 CDP 连接超时传给 Playwright，并为 browser/playwright 清理增加独立上限；保留原有错误分类。
3. Postgres 启动初始化失败时关闭并重置 app-level pool，再回退到 SQLite graph；调度器不得在失效 pool 上启动。
4. 为上述边界增加回归测试，覆盖响应捕获、分页索引、CDP 超时参数和启动失败后的 pool 清理。

## 验收标准

- 允许的 Creator Center API 路径带尾斜杠时，账号和笔记响应仍能被捕获。
- `page_num`/`pageNo` 的响应能推进分页，且原有 `page=0`、`page=1` 行为不回归。
- CDP 连接调用收到与同步超时一致的毫秒级 timeout；连接失败仍返回 `BROWSER_UNAVAILABLE`/现有分类，并释放 Playwright 资源。
- Playwright 清理阻塞时，连接失败仍能在清理上限内返回，不会吞掉原始连接错误。
- Postgres 初始化异常后 pool 不再处于 ready 状态，scheduler 不会以该 pool 启动，SQLite fallback 仍可建立。
- Creator Stats 定向测试、全量 pytest、Ruff、mypy（若环境提供）通过。

## 非目标

- 不改变 Creator Center 抓取页面、Cookie/签名策略、反风控节奏或持久化快照语义。
- 不把 fixture 重新引入产品 HTTP 同步路径。
- 不在没有真实生产错误日志的情况下调整调度延迟或放宽登录要求。
