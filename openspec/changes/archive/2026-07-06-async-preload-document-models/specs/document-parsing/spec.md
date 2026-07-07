## ADDED Requirements

### Requirement: Docling 模型内存异步预加载
系统 SHALL 在文档模型文件 bootstrap ready 后异步加载 Docling PDF 解析所需模型到进程内存，并且 MUST NOT 因内存预加载阻塞 FastAPI 应用启动完成。

#### Scenario: 文件模型 ready 后进入异步加载状态
- **WHEN** 后端启动阶段完成文档模型文件 bootstrap
- **AND** Docling artifacts readiness 为 `ready`
- **THEN** 系统 MUST 将 Docling 内存 readiness 标记为 `loading`
- **AND** 系统 MUST 启动后台任务加载 Docling PDF converter/pipeline
- **AND** FastAPI 应用启动 MUST NOT 等待该后台任务完成

#### Scenario: Docling 内存加载成功
- **WHEN** Docling 后台预加载任务成功初始化 PDF converter/pipeline
- **THEN** 系统 MUST 将 Docling 内存 readiness 标记为 `ready`
- **AND** 系统 MUST 保留已初始化的 converter 供后续解析复用
- **AND** 系统 MUST 记录结构化日志表达 Docling 模型已加载到内存

#### Scenario: Docling 内存加载失败
- **WHEN** Docling 后台预加载任务失败
- **THEN** 系统 MUST 将 Docling 内存 readiness 标记为 `unavailable`
- **AND** readiness 结果 MUST 包含加载失败诊断
- **AND** 系统 MUST 记录结构化错误日志表达失败原因

#### Scenario: 文件模型 unavailable 或 skipped 时不启动预加载
- **WHEN** 文档模型文件 bootstrap 的 Docling readiness 为 `unavailable` 或 `skipped`
- **THEN** 系统 MUST NOT 启动 Docling 内存预加载任务
- **AND** Docling 内存 readiness MUST 保持与文件 bootstrap 状态兼容

### Requirement: 解析请求使用 Docling 内存 readiness
系统 SHALL 在创建或执行需要 Docling 模型的解析任务前读取 Docling 内存 readiness，并在模型仍在加载或不可用时快速返回错误状态。

#### Scenario: 预加载期间创建 PDF 解析请求
- **WHEN** 用户请求解析需要 Docling artifacts 的上传文件
- **AND** Docling 内存 readiness 为 `loading`
- **THEN** API MUST 返回 `503 Service Unavailable`
- **AND** 响应 MUST 表达文档模型仍在加载中
- **AND** 系统 MUST NOT 创建会进入 Docling 懒加载路径的解析作业

#### Scenario: 预加载期间后台解析作业执行
- **WHEN** 后台解析作业需要 Docling artifacts
- **AND** Docling 内存 readiness 为 `loading`
- **THEN** 系统 MUST 将解析作业状态更新为 `failed`
- **AND** 解析作业 `error_code` MUST 为 `model_unavailable`
- **AND** 解析作业 `error_message` MUST 表达文档模型仍在加载中
- **AND** 系统 MUST NOT 调用 Docling converter 执行懒加载

#### Scenario: 预加载完成后解析复用 converter
- **WHEN** 后台解析作业需要 Docling artifacts
- **AND** Docling 内存 readiness 为 `ready`
- **AND** readiness 中存在已初始化 converter
- **THEN** 解析适配器 MUST 使用该 converter 执行解析
- **AND** 系统 MUST NOT 为该解析作业重新初始化 Docling PDF pipeline

#### Scenario: 纯文本解析不受 Docling loading 阻塞
- **WHEN** 用户请求解析可通过项目内纯文本路径处理的上传文件
- **AND** Docling 内存 readiness 为 `loading`
- **THEN** 系统 MUST 允许创建并执行解析任务
- **AND** 系统 MUST NOT 因 Docling 内存模型仍在加载而拒绝纯文本解析

### Requirement: 健康检查暴露模型内存加载状态
系统 SHALL 复用现有 `GET /api/health` 暴露文档模型内存 readiness 摘要，并且 MUST NOT 新增独立模型健康检查 endpoint。

#### Scenario: 健康检查返回 loading 摘要
- **WHEN** 文档模型内存预加载正在进行
- **AND** 客户端调用 `GET /api/health`
- **THEN** API MUST 返回 `200`
- **AND** 响应体的 `document_models` MUST 包含整体 `loading` 状态
- **AND** 响应体 MUST 表达 Docling 或 tokenizer 的组件级 `loading` 状态

