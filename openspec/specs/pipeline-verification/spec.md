# Pipeline Verification Spec

## Purpose

提供流水线存取验证功能，对已解析文档沿「向量 → 分块 → 文档」JOIN 链路还原全链路数据，执行完整性检查，确保解析、分块、向量化三阶段的数据一致性和可读性。

## Requirements

### Requirement: 流水线存取验证 API

系统 SHALL 提供 `GET /api/parsed-documents/{parsed_document_id}/pipeline-verification` 端点，对指定已解析文档执行完整的只读存取验证，沿「向量 → 分块 → 文档」JOIN 链路还原全链路数据，返回结构化验证结果。

#### Scenario: 完整 pipeline 文档验证成功

- **WHEN** 用户请求一个已完成解析、分块和向量化的文档的验证，且所有数据完整一致
- **THEN** 系统返回 HTTP 200，响应体包含文档信息、pipeline 三阶段作业状态（parse/chunk/embedding 均为 succeeded）、7 项完整性检查全部 passed、分块-向量对照 pairs 数组、以及统计摘要

#### Scenario: parsed_document 不存在或不属于当前用户

- **WHEN** 用户请求的 `parsed_document_id` 在数据库中不存在，或存在但不属于当前认证用户
- **THEN** 系统返回 HTTP 404，响应体 detail 为 "Parsed document not found"

#### Scenario: 文档存在但无成功的分块作业

- **WHEN** 用户请求验证一个已解析但分块作业不存在或分块作业状态非 succeeded 的文档
- **THEN** 系统返回 HTTP 404，响应体 detail 为 "No succeeded chunk job found for this document"

#### Scenario: 分块作业存在但无成功的向量化作业

- **WHEN** 用户请求验证一个已完成分块但向量化作业不存在或向量化作业状态非 succeeded 的文档
- **THEN** 系统返回 HTTP 404，响应体 detail 为 "No succeeded embedding job found for this document"

#### Scenario: pydoc 包含文本超出内联阈值存储在文件系统的 chunk

- **WHEN** 用户的文档包含 `text_storage_key` 非空但 `text` 为 NULL 的 chunk
- **THEN** 系统通过 `ChunkArtifactStorage.path_for()` 从文件系统读取文本内容，在 `chunk_text_availability` 检查中标记该 chunk 文本可读，`text_source` 字段返回 "file"

#### Scenario: 当前用户不可用

- **WHEN** `get_current_user()` 抛出 `CurrentUserUnavailableError`
- **THEN** 系统返回 HTTP 503，响应体 detail 为 "Current user is unavailable"

---

### Requirement: 分块-向量对应关系检查

系统 SHALL 在 `chunk_embedding_pairing` 检查中验证所有 chunk 都有对应的 embedding、所有 embedding 都能找到对应的 chunk，检测孤儿记录。

#### Scenario: 分块与向量一一对应

- **WHEN** 文档的所有 chunk 都有对应的 embedding，且所有 embedding 都能找到对应的 chunk
- **THEN** `chunk_embedding_pairing` 检查 passed 为 true，message 包含 "N/N 分块与向量一一对应，无孤儿记录"

#### Scenario: 存在孤儿 embedding

- **WHEN** 存在 `document_embeddings` 记录的 `chunk_id` 在 `document_chunks` 表中找不到对应记录（chunk 已被删除但 embedding 未清理）
- **THEN** `chunk_embedding_pairing` 检查 passed 为 false，message 明确报告孤儿 embedding 的数量和对应的 chunk_id

#### Scenario: 存在孤儿 chunk

- **WHEN** 存在 `document_chunks` 记录没有对应的 `document_embeddings` 记录（向量化作业不完整，部分 chunk 未成功向量化）
- **THEN** `chunk_embedding_pairing` 检查 passed 为 false，message 明确报告孤儿 chunk 的数量和 sequence_index

---

### Requirement: 向量维度一致性检查

系统 SHALL 在 `dimension_consistency` 检查中验证每条 embedding 记录的 `dimensions` 字段值与 job 声明的维度一致，且 `embedding_vector` 实际长度与声明维度匹配。

#### Scenario: 所有向量维度一致

- **WHEN** 所有 embedding 记录的 `dimensions` 字段与 embedding_job 的 `dimensions` 一致，且向量实际长度与声明维度匹配
- **THEN** `dimension_consistency` 检查 passed 为 true，message 包含 "所有 N 条向量维度均为 D"

#### Scenario: 部分向量维度不一致

- **WHEN** 存在 embedding 记录的 `dimensions` 字段值与 job 声明的维度不同，或 `embedding_vector` 实际长度与声明维度不匹配
- **THEN** `dimension_consistency` 检查 passed 为 false，message 明确报告哪条记录维度异常及实际值与期望值

---

### Requirement: 序号连续性检查

系统 SHALL 在 `sequence_continuity` 检查中验证 `sequence_index` 从 0 开始连续递增至 N-1（N 为 chunk_count），无重复、无跳号。

#### Scenario: 序号连续

- **WHEN** 文档的 sequence_index 从 0 到 N-1 连续无缺失
- **THEN** `sequence_continuity` 检查 passed 为 true，message 包含 "sequence_index 从 0 到 N-1 连续"

#### Scenario: 序号不连续（跳号）

- **WHEN** 文档的 sequence_index 存在跳号（如 0, 1, 3, 4，缺少 2）
- **THEN** `sequence_continuity` 检查 passed 为 false，message 明确报告缺失的序号

#### Scenario: 序号不连续（重复）

- **WHEN** 文档的 sequence_index 存在重复（如两条记录均为 sequence_index=1）
- **THEN** `sequence_continuity` 检查 passed 为 false，message 明确报告重复的序号

---

### Requirement: 分块文本可读性检查

系统 SHALL 在 `chunk_text_availability` 检查中遍历所有 chunk，确认每个 chunk 的文本都能成功获取（内联 text 非空或通过 `text_storage_key` 从文件系统成功读取）。

#### Scenario: 所有分块文本可读（全部内联）

- **WHEN** 所有 chunk 的 `text` 字段均非空（全部为内联存储）
- **THEN** `chunk_text_availability` 检查 passed 为 true，message 包含 "N/N 分块文本可读取（N 内联 + 0 文件存储）"

#### Scenario: 所有分块文本可读（混合存储）

- **WHEN** 部分 chunk 的 `text` 字段为 NULL 但 `text_storage_key` 有效，且文件系统中的对应文件存在且可读
- **THEN** `chunk_text_availability` 检查 passed 为 true，message 包含内联与文件存储的数量统计

#### Scenario: 部分分块文本不可读（文件缺失）

- **WHEN** 部分 chunk 的 `text` 字段为 NULL 且 `text_storage_key` 对应的文件系统文件不存在或无法读取
- **THEN** `chunk_text_availability` 检查 passed 为 false，message 明确报告哪些 chunk 的文本无法获取以及对应的 storage_key

---

### Requirement: 上下文增强文本可读性检查

系统 SHALL 在 `contextualized_text_availability` 检查中验证所有 chunk 的上下文增强文本均可成功获取（内联或文件系统），其检查逻辑与分块文本可读性检查相同但针对 `contextualized_text` / `contextualized_text_storage_key` 字段。

#### Scenario: 所有 contextualized_text 可读

- **WHEN** 所有 chunk 的 contextualized_text 均能成功获取
- **THEN** `contextualized_text_availability` 检查 passed 为 true

#### Scenario: 部分 contextualized_text 不可读

- **WHEN** 部分 chunk 的 contextualized_text 为 NULL 且 contextualized_text_storage_key 对应的文件不可读
- **THEN** `contextualized_text_availability` 检查 passed 为 false，message 明确报告哪些 chunk 的上下文增强文本缺失

---

### Requirement: Token 数有效性检查

系统 SHALL 在 `token_count_consistency` 检查中验证所有 chunk 和 embedding 的 `token_count` 字段均非 NULL 且大于 0。

#### Scenario: 所有 token_count 有效

- **WHEN** 所有 chunk 和 embedding 记录的 `token_count` 均非 NULL 且大于 0
- **THEN** `token_count_consistency` 检查 passed 为 true

#### Scenario: 部分 token_count 为空

- **WHEN** 存在 chunk 或 embedding 记录的 `token_count` 为 NULL
- **THEN** `token_count_consistency` 检查 passed 为 false，message 报告 token_count 为空的记录数量

#### Scenario: 部分 token_count 为 0

- **WHEN** 存在 chunk 或 embedding 记录的 `token_count` 为 0
- **THEN** `token_count_consistency` 检查 passed 为 false，message 报告 token_count 为 0 的记录数量

---

### Requirement: 嵌入模型一致性检查

系统 SHALL 在 `model_consistency` 检查中验证所有 embedding 记录使用相同的 `model` 字段值。

#### Scenario: 所有向量使用同一模型

- **WHEN** 所有 embedding 记录的 `model` 字段值一致
- **THEN** `model_consistency` 检查 passed 为 true，message 包含模型名称

#### Scenario: 混用不同嵌入模型

- **WHEN** 存在 embedding 记录的 `model` 字段值不一致（如同一文档的向量来自不同模型）
- **THEN** `model_consistency` 检查 passed 为 false，message 报告发现的多个不同模型名称

---

### Requirement: 验证响应结构

系统 SHALL 返回包含以下顶级字段的结构化 JSON 响应：`document`（文档元信息）、`pipeline`（三阶段作业状态）、`verification`（检查摘要与详细结果）、`pairs`（分块-向量对照数组）、`stats`（统计摘要）。

#### Scenario: 响应包含完整文档元信息

- **WHEN** 验证请求成功
- **THEN** `document` 字段包含 `parsed_document_id`、`title`、`original_filename`、`content_type`、`byte_size`

#### Scenario: 响应包含 pipeline 各阶段状态

- **WHEN** 验证请求成功
- **THEN** `pipeline` 字段包含 `parse_job`、`chunk_job`、`embedding_job` 三个子对象，每个子对象包含 `id`、`status`、以及对应的阶段特定字段（如 chunk_job 的 `chunker_name` 和 `chunk_count`、embedding_job 的 `model`、`dimensions` 和 `embedding_count`）

#### Scenario: 响应包含完整检查结果

- **WHEN** 验证请求成功
- **THEN** `verification` 字段包含 `passed`（布尔值，所有检查全部通过时为 true）、`total_checks`、`passed_checks`，以及 `checks` 数组，每个元素包含 `name`、`passed`、`message`

#### Scenario: 分块-向量对照 pair 按 sequence_index 排序

- **WHEN** 验证请求成功
- **THEN** `pairs` 数组中的元素按 `sequence_index` 升序排列，每个 pair 包含 `sequence_index`、`chunk`（id、text 截断、contextualized_text 截断、text_source、token_count、heading_path、page_numbers）、`embedding`（id、model、dimensions、vector_preview 前 5 维、token_count）

#### Scenario: 孤儿 embedding 的 pair 表示

- **WHEN** 存在孤儿 embedding（embedding 存在但 chunk 已删除）
- **THEN** 对应的 pair 中 `chunk` 字段为 `null`，`embedding` 字段包含孤儿 embedding 的信息

#### Scenario: 统计摘要准确反映数据状态

- **WHEN** 验证请求成功
- **THEN** `stats` 字段包含 `total_pairs`、`total_chunk_tokens`、`total_embedding_tokens`、`inline_text_count`、`file_storage_text_count`、`embedding_dimensions`、`embedding_model`

---

### Requirement: 前端验证页面

系统 SHALL 在 `/verify` 路由提供流水线存取验证页面，采用全宽居中布局 + 简化顶部导航栏（替代原有侧边栏），统一新视觉风格（品牌蓝 + Zinc Gray），保留全部现有验证功能。

#### Scenario: 页面加载时获取已解析文档列表

- **WHEN** 用户导航至 `/verify` 页面
- **THEN** 页面自动调用已有 API 获取当前用户的所有已解析文档列表，填充文档下拉选择器

#### Scenario: 用户选择文档并执行验证

- **WHEN** 用户从下拉列表选择一个文档并点击"执行验证"按钮
- **THEN** 页面调用 `GET /api/parsed-documents/{id}/pipeline-verification`，在加载期间显示骨架屏，请求完成后渲染文档信息、Pipeline 链路、验证摘要面板和分块-向量对照表

#### Scenario: 验证全部通过

- **WHEN** API 返回 `verification.passed` 为 true
- **THEN** 页面以绿色/通过样式展示所有 7 项检查，验证摘要面板显示 "7/7 通过"

#### Scenario: 部分检查失败

- **WHEN** API 返回部分检查 `passed` 为 false
- **THEN** 页面以红色/失败样式展示未通过的检查项，验证摘要面板显示实际通过数量和失败数量

#### Scenario: 选中文档无完整 pipeline

- **WHEN** API 返回 404 且 detail 指示某个阶段缺失
- **THEN** 页面显示错误详情，明确告知用户哪个 pipeline 阶段缺失（解析/分块/向量化），并建议下一步操作

#### Scenario: API 服务不可用

- **WHEN** API 返回 503 或其他 5xx 错误
- **THEN** 页面显示错误详情，建议用户稍后重试

#### Scenario: 无已解析文档时的空状态

- **WHEN** 当前用户没有任何已解析文档
- **THEN** 文档选择器显示空状态提示，引导用户先上传并解析文档

---

### Requirement: 验证页顶部导航栏
系统 SHALL 在 `/verify` 页面顶部显示简化导航栏，包含 knowra Logo、返回首页链接和"流程验证"页面标题，替代旧版全局 header。

#### Scenario: 顶部导航栏渲染
- **WHEN** 用户访问 `/verify`
- **THEN** 页面顶部显示导航栏，包含可点击的 knowra Logo（链接至 `/`）和"流程验证"标题

#### Scenario: 返回首页
- **WHEN** 用户点击导航栏中的 Logo 或返回链接
- **THEN** 系统导航至 `/`

---

### Requirement: 验证页视觉风格统一
系统 SHALL 将 `/verify` 页面的配色、卡片样式、按钮样式、排版统一为新的品牌蓝 + Zinc Gray 视觉规范。

#### Scenario: 按钮使用品牌蓝
- **WHEN** 验证页渲染"执行验证"主操作按钮
- **THEN** 按钮使用品牌蓝配色（`bg-blue-600 hover:bg-blue-700`）

#### Scenario: 卡片和面板统一圆角与阴影
- **WHEN** 验证页渲染卡片式面板
- **THEN** 卡片使用 `rounded-xl` 圆角和 `shadow-sm` 阴影

#### Scenario: 检查通过/失败状态色
- **WHEN** 验证结果显示检查通过或失败
- **THEN** 通过状态使用绿色（`text-emerald-600`），失败状态使用红色（`text-red-600`）
