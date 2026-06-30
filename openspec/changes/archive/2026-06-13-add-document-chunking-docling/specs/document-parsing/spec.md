## ADDED Requirements

### Requirement: 解析内部结果携带 transient DoclingDocument
系统 SHALL 在 Docling 解析适配器的内部结果中同时提供可持久化解析 payload 和只供当前后台任务使用的 transient `DoclingDocument`；Markdown 解析 SHALL 产出 transient `DoclingDocument`，TXT 解析 SHALL 使用纯文本兜底而不要求产出 transient `DoclingDocument`。

#### Scenario: Docling 解析返回 transient 文档对象
- **WHEN** Docling 解析适配器成功转换支持格式的文档
- **THEN** 解析内部结果 MUST 包含可持久化的 Markdown、纯文本、Docling JSON 和结构片段 payload
- **AND** 解析内部结果 MUST 包含当前解析运行内存中的 transient `DoclingDocument`

#### Scenario: Markdown 解析产出 transient 文档对象
- **WHEN** 上传文件为 Markdown
- **AND** 系统执行解析作业
- **THEN** 解析适配器 MUST 通过 Docling 生成当前解析运行内存中的 transient `DoclingDocument`
- **AND** 解析内部结果 MUST 保留该 transient `DoclingDocument` 以供自动分块使用
- **AND** 解析内部结果 MUST 仍包含可持久化的 Markdown、纯文本、Docling JSON 或等价结构化 JSON、结构片段 payload

#### Scenario: TXT 解析使用纯文本兜底
- **WHEN** 上传文件为 TXT
- **AND** 当前解析路径无法稳定产出 transient `DoclingDocument`
- **THEN** 解析内部结果 MUST 包含由原始纯文本生成的 Markdown、纯文本、等价结构化 JSON 和结构片段 payload
- **AND** 解析内部结果 MUST 明确表达缺少 transient `DoclingDocument`
- **AND** 系统 MUST NOT 为 TXT 从 `docling.json`、pickle 或其他已落地解析产物还原 transient `DoclingDocument`

#### Scenario: transient 文档对象不被持久化或暴露
- **WHEN** 系统保存解析产物、解析结果记录或返回解析 API 响应
- **THEN** 系统 MUST NOT 将 transient `DoclingDocument` 写入数据库
- **AND** 系统 MUST NOT 将 transient `DoclingDocument` 写入文件存储
- **AND** 系统 MUST NOT 通过 API 响应暴露 transient `DoclingDocument`

### Requirement: 解析成功路径接入自动分块
系统 SHALL 在解析后台任务成功保存解析结果后，优先将同一任务内的 transient `DoclingDocument` 交给文档分块服务执行首次分块；当 TXT 解析没有 transient `DoclingDocument` 时，系统 SHALL 使用纯文本兜底路径执行首次分块。

#### Scenario: 解析任务保存结果后触发分块服务
- **WHEN** `run_parse_job` 成功保存 `parsed_documents` 和 `document_segments`
- **AND** 分块功能配置为启用
- **AND** 解析内部结果包含 transient `DoclingDocument`
- **THEN** 解析任务 MUST 调用文档分块服务
- **AND** 解析任务 MUST 将同一个 transient `DoclingDocument` 对象传递给分块服务

#### Scenario: Markdown 解析后自动使用 DoclingDocument 分块
- **WHEN** `run_parse_job` 成功保存 Markdown 文件的 `parsed_documents` 和 `document_segments`
- **AND** 分块功能配置为启用
- **AND** 解析内部结果包含 Markdown 解析产生的 transient `DoclingDocument`
- **THEN** 解析任务 MUST 调用文档分块服务
- **AND** 解析任务 MUST 将该 transient `DoclingDocument` 传递给分块服务执行首次分块

#### Scenario: TXT 解析后使用纯文本兜底分块
- **WHEN** `run_parse_job` 成功保存 TXT 文件的 `parsed_documents` 和 `document_segments`
- **AND** 分块功能配置为启用
- **AND** 解析内部结果不包含 transient `DoclingDocument`
- **THEN** 解析任务 MUST 调用文档分块服务的纯文本兜底路径
- **AND** 纯文本兜底路径 MUST 使用解析结果中的纯文本或结构片段生成首次 chunk
- **AND** 解析任务 MUST NOT 为 TXT 从 `docling.json`、pickle 或其他已落地解析产物还原 transient `DoclingDocument`

#### Scenario: 分块禁用时解析保持成功
- **WHEN** `run_parse_job` 成功保存解析结果
- **AND** 分块功能配置为禁用
- **THEN** 解析作业 MUST 保持 `succeeded`
- **AND** 系统 MUST NOT 创建文档分块作业

#### Scenario: 分块失败不回滚解析结果
- **WHEN** `run_parse_job` 已成功保存解析结果
- **AND** 自动分块执行失败
- **THEN** 解析作业 MUST 保持 `succeeded`
- **AND** 分块作业 MUST 记录为 `failed`
- **AND** 已保存的 `parsed_documents` 和 `document_segments` MUST 保持可查询
