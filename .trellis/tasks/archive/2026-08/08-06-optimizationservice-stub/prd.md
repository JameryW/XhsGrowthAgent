# 删除死代码 OptimizationService stub

## 背景
`backend/services/optimization_service.py` 是未实现 stub：`analyze_titles` 返回空 dict + `# TODO: 实现标题分析逻辑`。`OptimizationService` 在 `backend/services/__init__.py` lazy 导出，但**全代码库零消费方**（grep backend/frontend/tests 无 import 无调用）。

死代码 + 未实现 stub，保留无价值，反误导后人以为有实现。

## 需求
删除 `OptimizationService` 死代码：
1. 删 `backend/services/optimization_service.py`
2. 从 `backend/services/__init__.py` `_LAZY_EXPORTS` 删 `OptimizationService` 条目
3. 从 `__all__` 删 `OptimizationService`

## 验证
- `from backend.services import RippleService` 等其余导出不受影响
- `pytest tests/ -q` 全绿（无测试引用它，确认无回归）
- `ruff check .` + `mypy backend` 绿
- grep 确认零残留引用

## 非目标
- 不实现 `analyze_titles`（无消费方，YAGNI）
- 不动其他 lazy 导出
