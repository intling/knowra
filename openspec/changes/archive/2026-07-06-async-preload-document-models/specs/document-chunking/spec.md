## ADDED Requirements

### Requirement: 分块 tokenizer 内存异步预加载
系统 SHALL 在文档模型文件 bootstrap ready 后异步加载默认分块 tokenizer 到进程内存，并且 MUST NOT 因 tokenizer 内存预加载阻塞 FastAPI 应用启动完成。

#### Scenario: tokenizer 文件 ready 后进入异步加载状态
- **WHEN** 后端启动阶段完成文档模型文件 bootstrap
- **AND** tokenizer 文件 readiness 为 `ready`
- **THEN** 系统 MUST 将 tokenizer 内存 readiness 标记为 `loading`
- **AND** 系统 MUST 启动后台任务加载 tokenizer
- **AND** FastAPI 应用启动 MUST NOT 等待该后台任务完成

#### Scenario: tokenizer 内存加载成功
- **WHEN** tokenizer 后台预加载任务成功创建分块 tokenizer
- **THEN** 系统 MUST 将 tokenizer 内存 readiness 标记为 `ready`
- **AND** 系统 MUST 保留已创建 tokenizer 供后续分块复用
- **AND** 系统 MUST 记录结构化日志表达 tokenizer 已加载到内存

#### Scenario: tokenizer 内存加载失败
- **WHEN** tokenizer 后台预加载任务失败
- **THEN** 系统 MUST 将 tokenizer 内存 readiness 标记为 `unavailable`
- **AND** readiness 结果 MUST 包含加载失败诊断
- **AND** 系统 MUST 记录结构化错误日志表达失败原因

### Requirement: 分块任务使用 tokenizer 内存 readiness
系统 SHALL 在自动分块和重新分块执行前读取 tokenizer 内存 readiness，并在 tokenizer 仍在加载或不可用时快速返回错误状态。

#### Scenario: 预加载期间自动分块执行
- **WHEN** 自动分块作业需要 tokenizer
- **AND** tokenizer 内存 readiness 为 `loading`
- **THEN** 系统 MUST 将分块作业状态更新为 `failed`
- **AND** 分块作业 `error_code` MUST 为 `model_unavailable`
- **AND** 分块作业 `error_message` MUST 表达 tokenizer 仍在加载中
- **AND** 系统 MUST NOT 在该分块作业内触发 tokenizer 懒加载

#### Scenario: 预加载期间请求重新分块
- **WHEN** 用户请求重新分块
- **AND** tokenizer 内存 readiness 为 `loading`
- **THEN** API MUST 返回 `503 Service Unavailable`
- **AND** 响应 MUST 表达 tokenizer 仍在加载中
- **AND** 系统 MUST NOT 创建新的重新分块作业

#### Scenario: 预加载完成后分块复用 tokenizer
- **WHEN** 分块作业需要 tokenizer
- **AND** tokenizer 内存 readiness 为 `ready`
- **AND** readiness 中存在已创建 tokenizer
- **THEN** 分块适配器 MUST 使用该 tokenizer 执行分块
- **AND** 系统 MUST NOT 为该分块作业重新加载 tokenizer
