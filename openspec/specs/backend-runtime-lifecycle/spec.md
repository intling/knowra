# backend-runtime-lifecycle Specification

## Purpose
TBD - created by archiving change add-graceful-model-shutdown. Update Purpose after archive.
## Requirements
### Requirement: 后端应用优雅关闭协调
系统 SHALL 在 FastAPI 应用生命周期结束时执行统一 graceful shutdown 流程，并通过该流程协调关闭状态、模型 runtime 清理和作业收尾。

#### Scenario: lifespan teardown 触发关闭流程
- **WHEN** ASGI server 因 `Ctrl+C`、`SIGTERM` 或正常应用停止进入 FastAPI lifespan teardown
- **THEN** 系统 MUST 将应用关闭状态标记为 `shutting_down`
- **AND** 系统 MUST 执行模型 runtime shutdown
- **AND** 系统 MUST 执行解析和分块作业收尾
- **AND** 系统 MUST 记录结构化日志表达关闭流程开始与结束

#### Scenario: 关闭流程幂等
- **WHEN** 应用关闭流程被重复调用
- **THEN** 系统 MUST NOT 重复释放同一模型资源导致异常
- **AND** 系统 MUST NOT 重复覆盖已经完成收尾的作业诊断
- **AND** 系统 MUST 记录结构化日志表达重复关闭调用被安全跳过或复用已有结果

#### Scenario: 不覆盖 ASGI server 信号管理
- **WHEN** 后端应用启动
- **THEN** 业务代码 MUST NOT 注册会覆盖 uvicorn 或 gunicorn graceful shutdown 行为的全局 `SIGINT`/`SIGTERM` handler
- **AND** 系统 MUST 通过 FastAPI lifespan teardown 接入可捕获关闭路径

### Requirement: 文档模型 runtime 清理
系统 SHALL 在 graceful shutdown 期间停止文档模型 runtime，释放应用持有的模型资源引用，并在限定时间内等待后台预加载线程结束。

#### Scenario: 清理已加载模型资源
- **WHEN** graceful shutdown 开始
- **AND** Docling converter 或 tokenizer 已加载到 runtime resource
- **THEN** 系统 MUST 将对应组件状态标记为 `shutting_down`
- **AND** 系统 MUST 对资源执行 best-effort cleanup
- **AND** 系统 MUST 清空 runtime 中保存的资源引用
- **AND** 系统 MUST 记录结构化日志表达释放的组件和资源数量

#### Scenario: 等待后台预加载线程
- **WHEN** graceful shutdown 开始
- **AND** 文档模型后台预加载线程仍在运行
- **THEN** 系统 MUST 最多等待配置的关闭超时时长
- **AND** 如果线程在超时前结束，系统 MUST 继续执行资源释放
- **AND** 如果线程未在超时前结束，系统 MUST 记录结构化 warning 日志并继续完成关闭流程

#### Scenario: 资源清理失败不阻断关闭
- **WHEN** 模型资源 cleanup hook 抛出异常
- **THEN** 系统 MUST 记录结构化 error 日志，包含组件名和错误信息
- **AND** 系统 MUST 继续清理其他资源
- **AND** 系统 MUST 继续执行作业收尾流程

#### Scenario: 未加载模型时安全关闭
- **WHEN** runtime 处于 `skipped`、`unavailable` 或尚未完成预加载的状态
- **THEN** 系统 MUST 安全完成 shutdown
- **AND** 系统 MUST NOT 因资源为空而抛出异常

### Requirement: 关闭期模型 readiness 摘要
系统 SHALL 在 graceful shutdown 期间让模型 readiness 摘要表达不可服务状态，并保持现有健康检查 API 兼容。

#### Scenario: health 暴露 shutting_down 状态
- **WHEN** 应用已进入 graceful shutdown
- **AND** 客户端调用 `GET /api/health`
- **THEN** API MUST 返回 `200`
- **AND** 响应体 `document_models.status` MUST 表达 `shutting_down`
- **AND** 响应体 MUST 表达 Docling 或 tokenizer 的组件级 `shutting_down` 状态

#### Scenario: 关闭期拒绝模型相关新工作
- **WHEN** 应用已进入 graceful shutdown
- **AND** 客户端请求创建需要模型的解析或分块工作
- **THEN** API MUST 返回 `503 Service Unavailable`
- **AND** 系统 MUST NOT 创建新的解析或分块作业

### Requirement: 优雅关闭配置
系统 SHALL 通过后端配置控制 graceful shutdown 的等待边界，并在配置缺省时使用安全默认值。

#### Scenario: 读取模型关闭超时配置
- **WHEN** 后端应用加载配置
- **THEN** 系统 MUST 读取模型 runtime shutdown timeout 配置
- **AND** 配置缺省时 MUST 使用有限的默认等待时长
- **AND** 配置值 MUST NOT 影响模型文件下载、解析限制或分块行为配置

#### Scenario: 文档说明不可捕获强杀边界
- **WHEN** 开发者阅读 README 或 `.env.example`
- **THEN** 文档 MUST 说明 graceful shutdown 覆盖 `Ctrl+C`、`SIGTERM` 和 ASGI lifespan teardown
- **AND** 文档 MUST 说明 `SIGKILL`、宿主机崩溃或容器强制杀死不在进程内清理承诺范围内

