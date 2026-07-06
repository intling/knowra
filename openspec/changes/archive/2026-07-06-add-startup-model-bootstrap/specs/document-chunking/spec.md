## ADDED Requirements

### Requirement: 分块 tokenizer 启动准备
系统 SHALL 将默认分块 tokenizer 纳入启动模型 bootstrap，并通过独立的 `DOCUMENT_MODEL_*` 变量声明 tokenizer 名称和缓存目录。

#### Scenario: 默认 tokenizer 已缓存时启动为 ready
- **WHEN** `DOCUMENT_MODEL_BOOTSTRAP_ENABLED` 为 `true`
- **AND** `DOCUMENT_MODEL_TOKENIZER_CACHE_DIR` 中已存在 `DOCUMENT_MODEL_TOKENIZER_NAME` 对应的 tokenizer 文件
- **THEN** 模型 bootstrap MUST 将 tokenizer readiness 标记为 `ready`
- **AND** 系统 MUST 记录结构化日志表达 tokenizer 已可用

#### Scenario: check_only 策略发现 tokenizer 缺失
- **WHEN** `DOCUMENT_MODEL_BOOTSTRAP_ENABLED` 为 `true`
- **AND** `DOCUMENT_MODEL_BOOTSTRAP_STRATEGY` 为 `check_only`
- **AND** `DOCUMENT_MODEL_TOKENIZER_NAME` 对应 tokenizer 未在 `DOCUMENT_MODEL_TOKENIZER_CACHE_DIR` 中可用
- **THEN** 模型 bootstrap MUST NOT 尝试下载 tokenizer
- **AND** 模型 bootstrap MUST 将 tokenizer readiness 标记为 `unavailable`
- **AND** readiness 结果 MUST 包含缺失的 tokenizer 名称

#### Scenario: download_missing 策略下载 tokenizer
- **WHEN** `DOCUMENT_MODEL_BOOTSTRAP_ENABLED` 为 `true`
- **AND** `DOCUMENT_MODEL_BOOTSTRAP_STRATEGY` 为 `download_missing`
- **AND** `DOCUMENT_MODEL_TOKENIZER_NAME` 对应 tokenizer 未在 `DOCUMENT_MODEL_TOKENIZER_CACHE_DIR` 中可用
- **THEN** 模型 bootstrap MUST 将 tokenizer 下载到 `DOCUMENT_MODEL_TOKENIZER_CACHE_DIR`
- **AND** 下载完成后系统 MUST 重新检查 tokenizer 可用性
- **AND** tokenizer 可用时 readiness MUST 标记为 `ready`

#### Scenario: tokenizer 准备不复用分块配置变量
- **WHEN** `DOCUMENT_MODEL_TOKENIZER_NAME` 未显式配置
- **AND** `DOCUMENT_CHUNK_TOKENIZER_MODEL` 已配置为非默认值
- **THEN** 模型 bootstrap MUST 使用 `DOCUMENT_MODEL_TOKENIZER_NAME` 的默认值或显式配置值
- **AND** 模型 bootstrap MUST NOT 使用 `DOCUMENT_CHUNK_TOKENIZER_MODEL` 作为 tokenizer 准备目标
- **AND** 模型 bootstrap MUST NOT 使用 `DOCUMENT_PARSE_DOCLING_CACHE_DIR` 作为 tokenizer cache 目录 fallback

### Requirement: 分块任务使用 tokenizer readiness
系统 SHALL 在自动分块和重新分块执行前读取 tokenizer readiness，并在 tokenizer 不可用时产生明确的模型不可用错误。

#### Scenario: tokenizer ready 时使用启动准备缓存
- **WHEN** 分块作业使用 `DOCUMENT_MODEL_TOKENIZER_NAME` 对应 tokenizer
- **AND** tokenizer readiness 为 `ready`
- **THEN** 分块适配器 MUST 使用 `DOCUMENT_MODEL_TOKENIZER_CACHE_DIR` 作为 tokenizer cache 目录
- **AND** 分块适配器 MUST NOT 使用 `DOCUMENT_PARSE_DOCLING_CACHE_DIR` 作为 tokenizer cache 目录

#### Scenario: tokenizer unavailable 时分块作业失败为模型不可用
- **WHEN** 分块作业需要 tokenizer
- **AND** tokenizer readiness 为 `unavailable`
- **THEN** 系统 MUST 将分块作业状态更新为 `failed`
- **AND** 分块作业 `error_code` MUST 为 `model_unavailable`
- **AND** 分块作业 `error_message` MUST 包含缺失 tokenizer 或模型准备失败原因
- **AND** 系统 MUST NOT 在该分块作业内触发 Transformers 或 Hugging Face 的隐式网络下载

#### Scenario: 重新分块请求使用未准备 tokenizer
- **WHEN** 当前用户请求重新分块
- **AND** 请求中的 tokenizer 与 `DOCUMENT_MODEL_TOKENIZER_NAME` 不一致
- **THEN** 系统 MUST 拒绝使用未准备 tokenizer 执行分块
- **AND** API 或分块作业错误 MUST 表达该 tokenizer 不在启动准备范围内
- **AND** 系统 MUST NOT 在请求路径中临时下载未准备 tokenizer
