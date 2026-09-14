# Context Compiler 验收基准（P1b-S5）

这份基准回答两个问题：**这次迁移到底省不省钱**，以及**它有没有把 prompt 组装弄坏**。
它完全离线、确定性——不启 workflow、不碰 store、不调模型，因此可以直接放进 CI 当门禁。

## 快速使用

```bash
# 完整报告（default + stress 两个场景）
python scripts/benchmarks/context_compiler_baseline.py

# CI 门禁形态：稳定性 + 漂移 + 覆盖度，任一失败退出码 1
python scripts/benchmarks/context_compiler_baseline.py --compare --drift-pct 5

# 常用开关
--budget 500        # 施加 token 预算，观察尾部裁剪
--stress-only       # 只跑 stress 场景
--json report.json  # 落盘 JSON 报告
--write-snapshot    # 刷新入库快照（有意变更后用）
```

CI 对应 job：`Context Compiler Baseline`（`.github/workflows/ci.yml`）。

## 两条轴

### 1. token 成本

对比对象是**迁移前的等价组装**：静态层文本 + 全部召回 body 原样追加——不去重、不重排、不裁剪。
差值就是去重 / 重排 / 预算裁剪真正带来的收益。

> **口径要点**：baseline 必须用 `parse_system_segments()` **之后**的静态文本。
> `<!-- ctx:l4_memory -->` 这类标记行不是语义文本，若按原文计算，等于把标记本身的
> token 算到编译器头上，对比就失真了。

### 2. 分层稳定性（四条不变量）

| 不变量 | 断言 |
|---|---|
| `repeat` | 相同输入重复编译，render 结果逐字节一致 |
| `shuffle` | 反转召回顺序不改变 render（rerank 确定性） |
| `dedup` | 重复召回不撑大 prompt |
| `budget` | 收紧预算从尾部（L5）开始裁，绝不碰 L0–L3 稳定前缀 |

每个 agent、每个场景都跑这四条。任一失败 → 退出码 1。

## 两个场景

- **default**：干净召回（无重复）。这里 delta 通常只有 +0.1%——纯连接符开销，因为没有可去重的内容。
  **迁移在干净召回下是 token 中性的**，这是正确的结果而不是"没效果"。
- **stress**：重复召回 + 长 L5 尾巴。这才是编译器真正赚钱的地方（去重 + 尾部裁剪）。

只跑 default 会得出"编译器没用"的错误结论——两个场景必须一起看。

### 当前实测（14 个 agent）

| 场景 | baseline | compiled | delta |
|---|---|---|---|
| default | 7366 | 7374 | +8（+0.1%） |
| stress | 8270 | 7646 | -624（-7.5%） |
| stress + `--budget 500` | 8270 | 7219 | -1051（-12.7%） |

单 agent stress 收益区间：-2.6%（evaluator，静态 policy 本身很大）到 -13.7%（blogger_scout）。

## 快照与漂移门禁

稳定性不变量能抓"编译器坏了"，抓不到"prompt 悄悄长胖 40%"或"某次改动把上下文饿瘦"。
所以另有入库快照 `scripts/benchmarks/baseline_snapshot.json`（14 agent × 2 场景，只存审计数字，不存渲染文本）。

- 漂移按 **绝对值** 判定，**膨胀和饿瘦都是回归**——两者都该被评审看见
- 默认阈值 5%（`--drift-pct`），粒度是 单个 agent × 场景
- agent 在快照里有、现在没了（或反之）→ 记为 `missing`，同样失败

### 有意变更怎么过门禁

改了 prompt 或编译器、token 数确实变了？**在同一个 PR 里刷新快照**，让数字变化出现在 diff 里：

```bash
python scripts/benchmarks/context_compiler_baseline.py --write-snapshot
git add scripts/benchmarks/baseline_snapshot.json
```

评审时看这个文件的 diff，就等于在看"这次改动让上下文多了/少了多少 token"。

## 覆盖度检查

`check_prompt_coverage()` 用 AST 扫描 `backend/agents/**` 里的 `prompt_file` 声明（不 import，
避免触发模块级副作用），与 prompt 目录比对：

- **missing**（agent 声明了但目录里没有）→ **失败**。`BaseAgent` 会兜底成空 system prompt，
  这是静默失效，必须拦住。
- **orphaned**（目录里有但没人声明）→ 打印提示，不失败（可能是过渡态）。

## 怎么加新 agent

1. 加 agent 类并声明 `prompt_file`，YAML 放进 `backend/config/prompts/`——覆盖度检查会核对两者
2. YAML 里有 `{memory_context}` / `{account_niche}` 之类需动态注入的段，就用
   `<!-- ctx:<layer> -->` 标记；无标记的 YAML 退化为单一 L0，逐字编译
3. 跑 `python scripts/benchmarks/context_compiler_baseline.py --write-snapshot` 把新 agent 记进快照
