# document-chunking Delta Spec

## MODIFIED: 重新分块 API

### Requirement: 重新分块 API
系统 SHALL 支持当前用户使用新的分块参数重新分块。API 端点创建 QUEUED 作业后 MUST 通过后台任务调度执行，并通过重新读取原始上传文件和重新解析来获得新的内存 `DoclingDocument`。

#### Scenario: 当前用户触发重新分块
- **WHEN** 当前用户请求 `POST /api/parsed-documents/{parsed_document_id}/rechunk`
- **AND** 解析结果属于当前用户
- **AND** 原始上传文件仍可读取
- **AND** tokenizer 处于 `ready` 状态
- **THEN** API MUST 返回 `202`
- **AND** 系统 MUST 创建状态为 `queued` 的新分块作业
- **AND** 系统 MUST 通过 FastAPI `BackgroundTasks` 调度后台执行任务
- **AND** 后台任务 MUST 重新读取原始上传文件并重新解析以获得新的内存 `DoclingDocument`
- **AND** 后台任务 MUST 使用请求中的分块参数或默认参数生成新的 chunk 集合
- **AND** 后台任务 MUST 在新 chunk 集合持久化完成后将新作业标记为 `succeeded` 并将被取代的旧作业标记为 `superseded`

#### Scenario: 重新分块失败时标记作业
- **WHEN** 后台执行任务无法完成重新分块（原始文件缺失、解析失败、分块异常等）
- **THEN** 系统 MUST 将新分块作业标记为 `failed`
- **AND** 分块作业 MUST 保存可诊断的 `error_code` 和 `error_message`
- **AND** 系统 MUST 保持旧 `succeeded` 分块作业为活跃结果

#### Scenario: 后台任务幂等保护
- **WHEN** 后台执行任务加载分块作业
- **AND** 作业状态已不是 `queued`（如已被其他执行实例处理或手动标记）
- **THEN** 后台任务 MUST 直接返回，不重复执行分块
- **AND** 后台任务 MUST NOT 修改该作业状态

#### Scenario: 运行中分块作业阻止重复重新分块
- **WHEN** 某解析结果已经存在 `queued` 或 `running` 的分块作业
- **AND** 当前用户再次请求重新分块
- **THEN** API MUST 返回 `409`
- **AND** 响应体 MUST 包含已有运行中分块作业信息
- **AND** 系统 MUST NOT 创建新的并发分块作业

#### Scenario: 重新分块运行中保留旧活跃结果
- **WHEN** 某解析结果存在旧的 `succeeded` 分块作业
- **AND** 该解析结果的新重新分块作业处于 `queued` 或 `running`
- **THEN** 系统 MUST 保持旧分块作业为活跃结果
- **AND** 默认 chunk 查询 MUST 继续返回旧分块作业的 chunk
- **AND** 系统 MUST NOT 在新作业成功前将旧分块作业标记为 `superseded`

#### Scenario: 重新分块失败保留旧活跃结果
- **WHEN** 某解析结果存在旧的 `succeeded` 分块作业
- **AND** 该解析结果的新重新分块作业执行失败
- **THEN** 系统 MUST 将新分块作业标记为 `failed`
- **AND** 系统 MUST 保持旧分块作业为活跃结果
- **AND** 默认 chunk 查询 MUST 继续返回旧分块作业的 chunk
- **AND** 系统 MUST NOT 因失败的新作业将旧分块作业标记为 `superseded`

#### Scenario: 新结果成功后取代旧分块作业
- **WHEN** 重新分块作业成功生成新的 chunk 集合
- **THEN** 系统 MUST 在新 chunk 集合持久化完成后将被取代的旧分块作业标记为 `superseded`
- **AND** 系统 MUST 保留旧 chunk 结果不主动删除
- **AND** 默认 chunk 查询 MUST 从旧 chunk 集合切换为返回新分块作业的 chunk

#### Scenario: 原始上传文件不可用时拒绝重新分块
- **WHEN** 当前用户请求重新分块
- **AND** 原始上传文件已删除或不可读取
- **THEN** API MUST 返回非 2xx 状态码
- **AND** 系统 MUST NOT 从旧解析产物还原文档对象来替代重新解析
- **AND** 系统 MUST NOT 创建分块作业或调度后台任务

#### Scenario: 重新分块不读取旧 docling.json
- **WHEN** 系统执行重新分块
- **THEN** 系统 MUST NOT 读取旧 `docling.json` 作为 `DoclingDocument` 还原输入
- **AND** 系统 MUST NOT 从 pickle 或其他已落地解析产物还原 `DoclingDocument`

## ADDED: 分块作业后台执行

### Requirement: 重新分块后台执行器
系统 SHALL 提供 `run_rechunk_job` 后台执行函数，负责加载 QUEUED 分块作业、重新解析原始文件、执行分块并持久化结果。

#### Scenario: 后台执行器成功执行重新分块
- **WHEN** `run_rechunk_job` 被调度执行
- **AND** 分块作业状态为 `queued`
- **AND** 原始上传文件存在且可解析
- **AND** 进程未进入 shutdown
- **THEN** 后台执行器 MUST 将作业状态更新为 `running`
- **AND** 后台执行器 MUST 从原始上传文件重新解析获得 `DoclingDocument`
- **AND** 后台执行器 MUST 使用 `DoclingParserAdapter` 执行解析
- **AND** 后台执行器 MUST 通过 `DocumentChunkingService.execute_queued_job()` 执行分块
- **AND** 作业 MUST 最终变为 `succeeded` 或 `failed`
- **AND** 成功时旧 `succeeded` 作业 MUST 被标记为 `superseded`

#### Scenario: 后台执行器因原始文件缺失而失败
- **WHEN** `run_rechunk_job` 被调度执行
- **AND** 原始上传文件已不可读取
- **THEN** 后台执行器 MUST 将作业标记为 `failed`
- **AND** 错误信息 MUST 表达原始文件不可用
- **AND** 后台执行器 MUST NOT 抛出未捕获异常

#### Scenario: 后台执行器因解析失败而失败
- **WHEN** `run_rechunk_job` 被调度执行
- **AND** `DoclingParserAdapter.parse()` 抛出异常
- **THEN** 后台执行器 MUST 将作业标记为 `failed`
- **AND** `error_code` MUST 为 `chunking_failed`
- **AND** 后台执行器 MUST 记录结构化错误日志
- **AND** 后台执行器 MUST NOT 抛出未捕获异常

#### Scenario: 后台执行器因 shutdown 快速失败
- **WHEN** `run_rechunk_job` 被调度执行
- **AND** 进程已进入 shutdown
- **THEN** 后台执行器 MUST 将作业标记为 `failed`
- **AND** `error_code` MUST 为 `process_shutdown`
- **AND** 后台执行器 MUST NOT 调用 parser 或 chunker

#### Scenario: 后台执行器支持依赖注入
- **WHEN** 测试代码调用 `run_rechunk_job`
- **AND** 传入了 `session_factory`、`parser` 等可选参数
- **THEN** 后台执行器 MUST 使用注入的依赖而非默认实现
- **AND** 这使得测试可以不依赖真实 Docling 解析和数据库连接

## ADDED: Service 执行引擎方法

### Requirement: 分块服务执行已创建作业
系统 SHALL 在 `DocumentChunkingService` 上提供 `execute_queued_job()` 方法，允许对 API 层已创建的 QUEUED 作业执行分块，并始终以 `supersede_previous=True` 模式运行。

#### Scenario: 对 QUEUED 作业执行分块
- **WHEN** 调用 `service.execute_queued_job(job=queued_job, parsed_document=..., transient_docling_document=...)`
- **AND** `queued_job` 状态为 `queued`
- **THEN** 方法 MUST 委托 `_run_job()` 执行完整分块流程
- **AND** `_run_job()` MUST 以 `supersede_previous=True` 模式运行
- **AND** 成功完成后作业状态 MUST 为 `succeeded`
- **AND** 旧的 `succeeded` 作业 MUST 被标记为 `superseded`

#### Scenario: execute_queued_job 不创建新作业
- **WHEN** 调用 `service.execute_queued_job()`
- **THEN** 方法 MUST NOT 调用 `_create_job()`
- **AND** 方法 MUST 直接使用传入的 `job` 参数执行分块

## REMOVED: 废弃的 Service 方法

### 移除项说明
以下 `DocumentChunkingService` 上的方法和类被移除，原因如下：

| 移除项 | 原因 |
|--------|------|
| `rechunk()` | 无人调用；校验逻辑与 API 层重复；作业创建与执行耦合 |
| `_parse_original_file()` | 重新解析逻辑移入 `run_rechunk_job`；其中的 `DeferredOriginalFileDocument` 分支为死路径 |
| `DeferredOriginalFileDocument` | 仅被上述死路径引用，从未真正工作 |
| `DocumentChunkOriginalFileUnavailableError` | 仅被 `rechunk()` 引用 |

#### Scenario: run_initial_chunking 行为不变
- **WHEN** 解析成功后触发 `service.run_initial_chunking()`
- **THEN** 方法 MUST 保持原有行为：创建作业 + 执行分块
- **AND** 方法 MUST NOT 受 `execute_queued_job` 新增或 `rechunk` 移除的影响
