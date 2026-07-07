## ADDED Requirements

### Requirement: 分块作业关闭收尾
系统 SHALL 在 graceful shutdown 期间对无法继续完成的文档分块作业写入明确失败状态，避免作业永久残留在 `queued` 或 `running`。

#### Scenario: 关闭时标记 queued 分块作业失败
- **WHEN** graceful shutdown 开始
- **AND** 存在状态为 `queued` 的文档分块作业
- **THEN** 系统 MUST 将该分块作业状态更新为 `failed`
- **AND** 分块作业 `error_code` MUST 为 `process_shutdown`
- **AND** 分块作业 `error_message` MUST 表达进程关闭导致作业未完成
- **AND** 分块作业 MUST 写入 `finished_at` 和更新 `updated_at`

#### Scenario: 关闭时标记 running 分块作业失败
- **WHEN** graceful shutdown 开始
- **AND** 存在状态为 `running` 的文档分块作业
- **THEN** 系统 MUST 将该分块作业状态更新为 `failed`
- **AND** 分块作业 `error_code` MUST 为 `process_shutdown`
- **AND** 分块作业 `error_message` MUST 表达进程关闭导致作业中断
- **AND** 分块作业 MUST 写入 `finished_at` 和更新 `updated_at`

#### Scenario: 不覆盖已完成分块作业
- **WHEN** graceful shutdown 开始
- **AND** 文档分块作业状态为 `succeeded`、`failed` 或 `superseded`
- **THEN** 系统 MUST NOT 修改该分块作业的状态、错误码或完成时间

### Requirement: 分块执行路径协作式响应关闭
系统 SHALL 在重新分块请求创建和分块执行关键边界检查应用关闭状态，并在关闭期快速失败。

#### Scenario: 关闭期拒绝创建重新分块作业
- **WHEN** 应用已进入 graceful shutdown
- **AND** 用户请求重新分块
- **THEN** API MUST 返回 `503 Service Unavailable`
- **AND** 系统 MUST NOT 创建新的文档分块作业
- **AND** 响应 MUST 表达服务正在关闭

#### Scenario: 分块作业进入 tokenizer 调用前发现关闭
- **WHEN** 分块作业准备调用 tokenizer 或 Docling HybridChunker
- **AND** 应用已进入 graceful shutdown
- **THEN** 系统 MUST 将分块作业状态更新为 `failed`
- **AND** 分块作业 `error_code` MUST 为 `process_shutdown`
- **AND** 系统 MUST NOT 调用 tokenizer 或 Docling HybridChunker

#### Scenario: 分块作业写入成功前发现关闭
- **WHEN** 分块作业已生成 chunk 但尚未写入成功状态
- **AND** 应用已进入 graceful shutdown
- **THEN** 系统 MUST 将分块作业状态更新为 `failed`
- **AND** 分块作业 `error_code` MUST 为 `process_shutdown`
- **AND** 系统 MUST NOT 将该分块作业标记为 `succeeded`
