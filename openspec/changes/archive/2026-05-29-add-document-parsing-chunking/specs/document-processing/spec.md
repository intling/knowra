## ADDED Requirements

### Requirement: 文档处理数据模型
系统 SHALL 持久化文档处理结果，区分原始上传文件、文档记录和可追溯 chunk，并为后续 embedding、检索和 RAG 引用保留稳定主键与来源信息。

#### Scenario: 创建文档处理表结构
- **WHEN** 数据库迁移执行完成
- **THEN** 数据库 MUST 存在 `documents` 表
- **AND** `documents` MUST 包含 `id`、`owner_user_id`、`uploaded_file_id`、`title`、`source_content_type`、`parser_name`、`parser_version`、`chunker_name`、`chunker_version`、`tokenizer_name`、`tokenizer_version`、`status`、`chunk_count`、`total_chars`、`content_sha256`、`metadata_json`、`error_message`、`deleted_at`、`created_at`、`updated_at` 字段
- **AND** 数据库 MUST 存在 `document_chunks` 表
- **AND** `document_chunks` MUST 包含 `id`、`document_id`、`owner_user_id`、`chunk_index`、`content`、`content_sha256`、`char_start`、`char_end`、`token_count`、`source_locator_json`、`metadata_json`、`created_at`、`updated_at` 字段

#### Scenario: 文档关联上传文件与当前用户
- **WHEN** 系统创建文档记录
- **THEN** `documents.uploaded_file_id` MUST 引用被处理的 `uploaded_files.id`
- **AND** `documents.owner_user_id` MUST 来自对应上传记录的 `owner_user_id`
- **AND** 系统 MUST NOT 使用客户端提交的用户归属字段决定文档归属

#### Scenario: chunk 保留可追溯来源
- **WHEN** 系统创建文档 chunk
- **THEN** 每个 chunk MUST 关联 `document_id`
- **AND** 每个 chunk MUST 保存 `owner_user_id`
- **AND** 每个 chunk MUST 保存文档内稳定的 `chunk_index`
- **AND** 每个 chunk MUST 保存规范化文本中的 `char_start` 和 `char_end`
- **AND** 每个 chunk MUST 保存可定位来源位置的 `source_locator_json`

### Requirement: 从已上传文件创建文档
系统 SHALL 提供从已上传原始文件创建文档与 chunks 的 API，并只允许处理当前用户拥有且已成功存储的上传文件。

#### Scenario: 成功创建文档与 chunks
- **WHEN** 当前用户向 `POST /api/documents` 提交包含 `uploaded_file_id` 的请求
- **AND** 该上传文件属于当前用户
- **AND** 该上传文件的 `status` 为 `stored`
- **AND** 系统成功解析并分块该文件
- **THEN** API MUST 返回 `201`
- **AND** 响应体 MUST 包含文档元数据
- **AND** 文档状态 MUST 为 `parsed`
- **AND** 系统 MUST 持久化与 `chunk_count` 一致数量的 chunks

#### Scenario: 上传文件不存在或不属于当前用户
- **WHEN** 当前用户向 `POST /api/documents` 提交不存在或不属于当前用户的 `uploaded_file_id`
- **THEN** API MUST 返回 `404`
- **AND** 系统 MUST NOT 泄露其他用户上传文件是否存在
- **AND** 系统 MUST NOT 创建文档或 chunks

#### Scenario: 上传文件未处于 stored 状态
- **WHEN** 当前用户向 `POST /api/documents` 提交属于当前用户但状态不是 `stored` 的 `uploaded_file_id`
- **THEN** API MUST 返回 `409`
- **AND** 系统 MUST NOT 创建 `parsed` 文档
- **AND** 系统 MUST NOT 创建可检索 chunks

### Requirement: 重复处理冲突
系统 SHALL 阻止同一 `uploaded_file_id` 被重复处理为多套文档 chunks，并通过冲突响应返回已有文档元数据。

#### Scenario: 重复处理同一上传文件
- **WHEN** 当前用户向 `POST /api/documents` 提交已经存在文档记录的 `uploaded_file_id`
- **THEN** API MUST 返回 `409 Conflict`
- **AND** 响应体 MUST 包含 `existing_document`
- **AND** `existing_document` MUST 包含 `id`、`uploaded_file_id`、`title`、`status`、`chunk_count`、`parser_name`、`parser_version`、`chunker_name`、`chunker_version`、`tokenizer_name`、`tokenizer_version`、`created_at`、`updated_at`
- **AND** 系统 MUST NOT 创建重复的文档记录或 chunks

### Requirement: 首批文件解析格式
系统 SHALL 首批支持 TXT、Markdown、PDF、DOCX、PPT/PPTX 的文本解析，并为每种格式生成规范化文本和来源定位信息。

#### Scenario: 解析 TXT 文件
- **WHEN** 系统处理内容类型为 `text/plain` 或扩展名为 `.txt` 的上传文件
- **THEN** 系统 MUST 按文本文件解析内容
- **AND** 解码失败时 MUST 创建或返回 `failed` 文档元数据

#### Scenario: 解析 Markdown 文件
- **WHEN** 系统处理内容类型为 `text/markdown` 或扩展名为 `.md` 的上传文件
- **THEN** 系统 MUST 保留 Markdown 文本内容
- **AND** 系统 MUST 在可行时把标题路径写入 chunk 来源或元数据

#### Scenario: 解析具备文本层的 PDF 文件
- **WHEN** 系统处理内容类型为 `application/pdf` 或扩展名为 `.pdf` 的上传文件
- **THEN** 系统 MUST 尝试逐页抽取文本
- **AND** chunk 的 `source_locator_json` MUST 至少能够表达 PDF 页码

#### Scenario: 扫描版 PDF 无法抽取文本
- **WHEN** 系统处理 PDF 文件但无法抽取有效文本
- **THEN** 系统 MUST 创建或返回 `failed` 文档元数据
- **AND** 失败原因 MUST 表达 PDF 缺少可抽取文本或需要 OCR
- **AND** 系统 MUST NOT 创建 `parsed` 文档或可检索 chunks

#### Scenario: 解析 DOCX 文件
- **WHEN** 系统处理内容类型为 `application/vnd.openxmlformats-officedocument.wordprocessingml.document` 或扩展名为 `.docx` 的上传文件
- **THEN** 系统 MUST 抽取标题、段落和主要表格文本
- **AND** chunk 的 `source_locator_json` MUST 至少能够表达段落序号或结构路径

#### Scenario: 解析 PPT 或 PPTX 文件
- **WHEN** 系统处理 PowerPoint 上传文件
- **THEN** 系统 MUST 按幻灯片顺序抽取标题、文本框和备注文本
- **AND** chunk 的 `source_locator_json` MUST 至少能够表达 slide index

### Requirement: BPE 分块
系统 SHALL 使用 BPE tokenizer 控制 chunk 大小和重叠窗口，并记录分块所需的版本信息。

#### Scenario: 成功生成 BPE chunks
- **WHEN** 系统成功解析上传文件为规范化文本
- **THEN** 系统 MUST 使用 BPE tokenizer 生成 chunks
- **AND** 每个 chunk MUST 保存 `token_count`
- **AND** 文档记录 MUST 保存 `tokenizer_name` 和 `tokenizer_version`
- **AND** 文档记录 MUST 保存 `chunker_name` 和 `chunker_version`

#### Scenario: chunk 顺序稳定
- **WHEN** 系统对同一规范化文本使用相同 parser、chunker、tokenizer 和参数进行处理
- **THEN** 系统 MUST 生成稳定的 chunk 顺序
- **AND** `chunk_index` MUST 从 0 开始递增

#### Scenario: 分块结果支持引用定位
- **WHEN** 系统生成 chunk
- **THEN** chunk MUST 保存 `content_sha256`
- **AND** chunk MUST 保存规范化文本字符范围
- **AND** chunk MUST 保存来源定位信息

### Requirement: 文档处理失败状态
系统 SHALL 持久化文档处理失败状态，使用户能够在资料列表中看到失败文档及原因，同时避免失败文档进入检索消费链路。

#### Scenario: 解析失败生成 failed 文档
- **WHEN** 系统无法解析上传文件或解析结果为空
- **THEN** 系统 MUST 创建或返回状态为 `failed` 的文档元数据
- **AND** `error_message` MUST 包含用户可理解的失败原因
- **AND** 系统 MUST NOT 创建可检索 chunks

#### Scenario: failed 文档不会被 chunk 查询消费
- **WHEN** 当前用户请求 failed 文档的 chunks
- **THEN** API MUST 返回空列表或非 2xx 错误
- **AND** 系统 MUST NOT 把 failed 文档暴露为可检索内容

### Requirement: 文档资料列表
系统 SHALL 提供当前用户的文档资料列表，展示成功解析和解析失败的文档状态。

#### Scenario: 列出 parsed 和 failed 文档
- **WHEN** 当前用户请求 `GET /api/documents`
- **THEN** API MUST 返回当前用户的文档列表
- **AND** 列表 MUST 包含 `parsed` 文档
- **AND** 列表 MUST 包含 `failed` 文档
- **AND** 每个 failed 文档项 MUST 包含失败原因

#### Scenario: 资料列表不泄露其他用户文档
- **WHEN** 当前用户请求 `GET /api/documents`
- **THEN** API MUST NOT 返回其他用户的文档记录

### Requirement: 文档详情与 chunks 查询
系统 SHALL 提供文档详情和 chunks 查询 API，用于资料详情、调试和后续检索验证。

#### Scenario: 读取文档详情
- **WHEN** 当前用户请求属于自己的 `GET /api/documents/{id}`
- **THEN** API MUST 返回文档元数据
- **AND** 响应体 MUST 包含来源上传文件信息或来源上传文件标识

#### Scenario: 读取文档 chunks
- **WHEN** 当前用户请求属于自己的 parsed 文档 `GET /api/documents/{id}/chunks`
- **THEN** API MUST 返回按 `chunk_index` 升序排列的 chunks
- **AND** 每个 chunk MUST 包含内容、顺序、token 数、字符范围和来源定位信息

#### Scenario: 禁止读取其他用户文档
- **WHEN** 当前用户请求不属于自己的文档详情或 chunks
- **THEN** API MUST 返回 `404`
- **AND** 系统 MUST NOT 泄露其他用户文档是否存在

### Requirement: 成功文档一致性
系统 SHALL 保证成功解析文档与 chunks 的持久化一致性，避免后续检索消费半成品数据。

#### Scenario: 成功文档 chunk 数一致
- **WHEN** 系统返回状态为 `parsed` 的文档
- **THEN** 该文档 MUST 拥有与 `chunk_count` 一致数量的 chunks

#### Scenario: chunk 写入失败回滚
- **WHEN** 系统在写入 chunks 过程中失败
- **THEN** 系统 MUST NOT 保留状态为 `parsed` 但 chunks 不完整的文档
- **AND** 系统 MUST 回滚该次处理的半成品数据或记录为 `failed`
