# brainstorm: support PDF upload in brief mode

## Goal

在商单 brief 模式中支持上传 PDF 文件，提取文本后传入 brief_analyzer 解析，替代/补充现有的纯文本输入方式。

## What I already know

* **后端已实现**：`POST /brief/upload/{thread_id}` 端点已存在（workflow.py:913-962）
  - 支持 PDF 文件上传，使用 pdfplumber 提取文本
  - pdfplumber 提取质量差时，自动 fallback 到多模态 LLM（_extract_pdf_with_llm）
  - 提取结果写入 `state["brief_content"]["raw_text"]`，`source_type` 设为 "pdf"
* **后端 state 已支持**：`BriefContent` substate 已有 `source_type: str  # "text" | "pdf" | "image"`
* **前端缺失**：WorkflowStartForm.vue 只有 textarea，没有文件上传组件
* **前端 store 缺失**：workflow.ts 的 `startWorkflow` 只传 `brief_text`，没有调用 `/brief/upload` API
* **前端 API 层缺失**：没有 `uploadBriefFile` 方法
* **pdfplumber 已在依赖中**：后端代码已 import pdfplumber

## Assumptions (temporary)

* PDF 上传在 workflow 启动后、brief_analyzer 执行前进行（先 start → 再 upload → 再 resume）
* 或者：PDF 上传可以在 startWorkflow 时一并提交（更流畅的 UX）
* 文件大小限制：10MB 以内
* 只支持 PDF，暂不支持图片/Word

## Open Questions

* ~~PDF 上传的 UX 流程：start 时一起提交 vs start 后单独上传？~~ → 两者都支持
* ~~是否需要上传进度条？~~ → 不需要（PDF 通常不大）
* ~~是否需要预览提取的文本内容？~~ → 预览 + 确认：显示提取文本，用户点"确认"后才触发 brief_analyzer

## Decision (ADR-lite)

**Context**: 用户可能在创建 workflow 时就准备好 PDF，也可能在 workflow 运行中才上传
**Decision**: 两种场景都支持 — WorkflowStartForm 里可上传，运行中 awaiting_brief 阶段也可上传/替换
**Consequences**: 需要共享的上传组件，store 需要处理两种调用时机

## Requirements (evolving)

* 前端 WorkflowStartForm 添加文件上传组件（brief 模式下显示）
* 前端 workflow 运行页面也支持上传/替换 PDF（awaiting_brief 阶段）
* 前端 API 层添加 `uploadBriefFile(threadId, file)` 方法
* 前端 store 添加上传逻辑，提取文本后更新 state
* 上传成功后自动触发 brief_analyzer 解析
* 错误处理：文件过大、格式不支持、提取失败
* 上传与文本输入互斥：上传 PDF 后清空/禁用文本框，手动输入文本后清除已上传文件
* 上传成功后显示提取文本预览（可编辑），用户确认后才触发 brief_analyzer
* 预览区域支持编辑提取的文本（修正 OCR/提取错误）
* 提取失败时回退到文本输入模式，提示用户手动粘贴
* 上传组件用 `accept=".pdf"` 非硬编码，预留后续扩展 Word/图片
* 文件大小限制 10MB，超限时提示

## Acceptance Criteria (evolving)

* [ ] brief 模式下可以选择上传 PDF 文件或手动输入文本
* [ ] 上传 PDF 后，提取的文本显示在预览区域（可编辑）
* [ ] 用户确认后才触发 brief_analyzer 解析
* [ ] 提取失败时回退到文本输入模式并提示
* [ ] 文件超 10MB 时拒绝并提示
* [ ] 上传组件 accept=".pdf"，预留扩展空间
* [ ] 上传失败时有明确的错误提示

## Definition of Done (team quality bar)

* Tests added/updated (unit/integration where appropriate)
* Lint / typecheck / CI green
* Docs/notes updated if behavior changes

## Out of Scope (explicit)

* Word/Excel 文件上传（但上传组件预留扩展点）
* 图片 OCR 上传（后端 LLM fallback 已有，前端暂不开放）
* PDF 文件存储/持久化（只提取文本，不保存原文件）
* 上传进度条（PDF 通常 <10MB，秒传）

## Technical Notes

* 后端端点：`POST /brief/upload/{thread_id}`（workflow.py:913）
* 后端 PDF 提取：`_extract_pdf_text`（pdfplumber）+ `_extract_pdf_with_llm`（fallback）
* 前端表单：`WorkflowStartForm.vue`
* 前端 store：`workflow.ts`
* 前端 API：需确认 api 层文件位置
* State substate：`BriefContent.source_type` 已支持 "pdf"
