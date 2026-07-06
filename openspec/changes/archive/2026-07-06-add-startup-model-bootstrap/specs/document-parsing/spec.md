## ADDED Requirements

### Requirement: 文档模型启动配置隔离
系统 SHALL 使用独立的 `DOCUMENT_MODEL_*` 环境变量配置启动后的文档模型准备流程，并且 MUST NOT 复用、扩展或 fallback 到既有 `DOCUMENT_PARSE_*` 或 `DOCUMENT_CHUNK_*` 变量作为模型 bootstrap 配置来源。

#### Scenario: 读取独立模型准备配置
- **WHEN** 后端应用启动
- **THEN** 系统 MUST 从配置中读取 `DOCUMENT_MODEL_BOOTSTRAP_ENABLED`
- **AND** 系统 MUST 从配置中读取 `DOCUMENT_MODEL_BOOTSTRAP_STRATEGY`
- **AND** 系统 MUST 从配置中读取 `DOCUMENT_MODEL_BOOTSTRAP_FAILURE_POLICY`
- **AND** 系统 MUST 从配置中读取 `DOCUMENT_MODEL_DOCLING_ARTIFACT_DIR`
- **AND** 系统 MUST 从配置中读取 `DOCUMENT_MODEL_HF_ENDPOINT`
- **AND** 系统 MUST 从配置中读取 `DOCUMENT_MODEL_DOCLING_REQUIRED_MODELS`
- **AND** 系统 MUST 从配置中读取 `DOCUMENT_MODEL_TOKENIZER_NAME`
- **AND** 系统 MUST 从配置中读取 `DOCUMENT_MODEL_TOKENIZER_CACHE_DIR`

#### Scenario: 不复用既有解析或分块变量
- **WHEN** `DOCUMENT_MODEL_*` 变量未显式配置
- **AND** 既有 `DOCUMENT_PARSE_*` 或 `DOCUMENT_CHUNK_*` 变量已配置为非默认值
- **THEN** 模型 bootstrap MUST 使用 `DOCUMENT_MODEL_*` 默认值或显式配置值
- **AND** 模型 bootstrap MUST NOT 使用 `DOCUMENT_PARSE_DOCLING_CACHE_DIR` 作为 Docling artifacts 目录 fallback
- **AND** 模型 bootstrap MUST NOT 使用 `DOCUMENT_CHUNK_TOKENIZER_MODEL` 作为 tokenizer 名称 fallback
- **AND** 模型 bootstrap MUST NOT 使用任何既有解析或分块变量作为下载策略、镜像地址或模型目录来源

#### Scenario: 配置 Hugging Face 镜像地址
- **WHEN** `DOCUMENT_MODEL_HF_ENDPOINT` 配置为非空地址
- **AND** 模型 bootstrap 需要检查或下载 Hugging Face 模型
- **THEN** 系统 MUST 在调用 Hugging Face Hub 或 Docling 下载逻辑前使用该地址配置 Hugging Face endpoint
- **AND** 系统 MUST NOT 在代码中硬编码镜像地址

### Requirement: Docling 模型启动准备
系统 SHALL 在后端应用启动后的模型 bootstrap 流程中检查 Docling 文档解析所需 artifacts，并按配置策略处理缺失模型。

#### Scenario: Docling 模型已存在时启动为 ready
- **WHEN** `DOCUMENT_MODEL_BOOTSTRAP_ENABLED` 为 `true`
- **AND** `DOCUMENT_MODEL_DOCLING_ARTIFACT_DIR` 中已存在 `DOCUMENT_MODEL_DOCLING_REQUIRED_MODELS` 声明的全部 Docling artifacts
- **THEN** 模型 bootstrap MUST 将 Docling readiness 标记为 `ready`
- **AND** 系统 MUST 记录结构化日志表达 Docling 模型已可用

#### Scenario: check_only 策略发现模型缺失
- **WHEN** `DOCUMENT_MODEL_BOOTSTRAP_ENABLED` 为 `true`
- **AND** `DOCUMENT_MODEL_BOOTSTRAP_STRATEGY` 为 `check_only`
- **AND** 一个或多个 required Docling 模型缺失
- **THEN** 模型 bootstrap MUST NOT 尝试下载缺失模型
- **AND** 模型 bootstrap MUST 将 Docling readiness 标记为 `unavailable`
- **AND** readiness 结果 MUST 包含缺失模型清单

#### Scenario: download_missing 策略下载缺失模型
- **WHEN** `DOCUMENT_MODEL_BOOTSTRAP_ENABLED` 为 `true`
- **AND** `DOCUMENT_MODEL_BOOTSTRAP_STRATEGY` 为 `download_missing`
- **AND** 一个或多个 required Docling 模型缺失
- **THEN** 模型 bootstrap MUST 将缺失模型下载到 `DOCUMENT_MODEL_DOCLING_ARTIFACT_DIR`
- **AND** 下载完成后系统 MUST 重新检查 required Docling 模型
- **AND** 全部 required Docling 模型可用时 readiness MUST 标记为 `ready`

#### Scenario: fail_fast 策略阻止不可用模型启动
- **WHEN** 模型 bootstrap 完成后 Docling readiness 为 `unavailable`
- **AND** `DOCUMENT_MODEL_BOOTSTRAP_FAILURE_POLICY` 为 `fail_fast`
- **THEN** 后端应用 MUST 中止启动
- **AND** 系统 MUST 记录结构化错误日志表达缺失模型和配置建议

#### Scenario: degraded 策略允许降级启动
- **WHEN** 模型 bootstrap 完成后 Docling readiness 为 `unavailable`
- **AND** `DOCUMENT_MODEL_BOOTSTRAP_FAILURE_POLICY` 为 `degraded`
- **THEN** 后端应用 MUST 继续启动
- **AND** 系统 MUST 保留 Docling readiness 的不可用状态供解析任务读取
- **AND** 系统 MUST 记录结构化告警日志表达后续解析可能失败

#### Scenario: 禁用模型 bootstrap
- **WHEN** `DOCUMENT_MODEL_BOOTSTRAP_ENABLED` 为 `false`
- **THEN** 系统 MUST 跳过启动模型检查和下载
- **AND** readiness MUST 标记为 `skipped`
- **AND** 系统 MUST NOT 因未执行模型 bootstrap 而复用既有解析或分块变量作为替代配置

### Requirement: 解析任务使用模型 readiness
系统 SHALL 在执行需要 Docling 模型 artifacts 的文档解析前读取启动模型 readiness，并在模型不可用时产生明确的模型不可用错误。

#### Scenario: 模型 ready 时使用启动准备目录解析
- **WHEN** 文档解析作业需要 Docling 模型 artifacts
- **AND** Docling readiness 为 `ready`
- **THEN** 解析适配器 MUST 使用 `DOCUMENT_MODEL_DOCLING_ARTIFACT_DIR` 作为 Docling artifacts 目录
- **AND** 解析适配器 MUST NOT 使用 `DOCUMENT_PARSE_DOCLING_CACHE_DIR` 作为该解析运行的模型 artifacts 目录

#### Scenario: 模型 unavailable 时解析作业失败为模型不可用
- **WHEN** 文档解析作业需要 Docling 模型 artifacts
- **AND** Docling readiness 为 `unavailable`
- **THEN** 系统 MUST 将解析作业状态更新为 `failed`
- **AND** 解析作业 `error_code` MUST 为 `model_unavailable`
- **AND** 解析作业 `error_message` MUST 包含缺失模型或模型准备失败原因
- **AND** 系统 MUST NOT 在该解析作业内触发 Docling 或 Hugging Face 的隐式网络下载

#### Scenario: 不需要 Docling artifacts 的文本解析不被 Docling readiness 阻塞
- **WHEN** 上传文件可以通过项目内纯文本兜底路径解析
- **AND** Docling readiness 为 `unavailable`
- **THEN** 系统 MUST 允许该解析路径继续执行
- **AND** 系统 MUST NOT 因 Docling artifacts 缺失而拒绝纯文本兜底解析

### Requirement: 现有健康检查暴露文档模型 readiness
系统 SHALL 复用现有 `GET /api/health` 暴露文档模型 readiness 摘要，并且 MUST NOT 新增独立的 `/api/health/document-models` endpoint。

#### Scenario: 健康检查返回模型 ready 摘要
- **WHEN** 后端应用启动后文档模型 bootstrap readiness 为 `ready`
- **AND** 客户端调用 `GET /api/health`
- **THEN** API MUST 返回 `200`
- **AND** 响应体 MUST 保留既有健康检查字段
- **AND** 响应体 MUST 包含文档模型 readiness 摘要
- **AND** 文档模型 readiness 摘要 MUST 表达 Docling artifacts 和 tokenizer 均为 `ready`

#### Scenario: 健康检查返回模型 degraded 摘要
- **WHEN** 后端应用以 `degraded` 策略启动
- **AND** 文档模型 bootstrap readiness 为 `unavailable`
- **AND** 客户端调用 `GET /api/health`
- **THEN** API MUST 返回 `200`
- **AND** 响应体 MUST 包含文档模型 readiness 摘要
- **AND** 文档模型 readiness 摘要 MUST 包含不可用状态和缺失模型诊断

#### Scenario: 健康检查返回模型 skipped 摘要
- **WHEN** `DOCUMENT_MODEL_BOOTSTRAP_ENABLED` 为 `false`
- **AND** 客户端调用 `GET /api/health`
- **THEN** API MUST 返回 `200`
- **AND** 响应体 MUST 包含文档模型 readiness 摘要
- **AND** 文档模型 readiness 摘要 MUST 表达模型 bootstrap 已跳过

#### Scenario: 不新增独立模型健康检查 endpoint
- **WHEN** 客户端调用 `GET /api/health/document-models`
- **THEN** 系统 MUST NOT 提供该 endpoint 作为本变更的公共 API
- **AND** 模型 readiness MUST 只能通过既有 `GET /api/health` 的响应摘要暴露
