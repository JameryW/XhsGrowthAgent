"""API 模块 — FastAPI 应用入口.

提供 REST API 接口:
- /api/workflow: 工作流控制
- /api/review: 人工审核
- /api/analytics: 数据分析
"""

from xhs_growth.api.app import app

__all__ = ["app"]