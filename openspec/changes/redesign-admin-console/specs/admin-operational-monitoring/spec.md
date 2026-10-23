## ADDED Requirements

### Requirement: 统一只读任务列表
`GET /api/admin/jobs` SHALL 返回三类任务的统一安全投影，支持 `kind,status,owner_user_id,from,to,offset,limit`；默认最近 24 小时、按创建时间过滤、时间范围最长 31 天，并按 `(created_at DESC,id DESC)` 稳定排序。该能力 MUST 要求 `operations:read`。

#### Scenario: 分阶段查询
- **WHEN** 管理员筛选某账号的失败向量化任务
- **THEN** 返回 MUST 仅包含符合条件的任务，总数 MUST 为全量匹配数量
- **AND** 统一字段 MUST 包含 kind、任务 ID、上传 ID、所属账号 ID、状态、时间、耗时和安全错误码
- **AND** 无匹配返回 200 空列表，非法枚举或时间范围返回有原因的 422

#### Scenario: 元数据边界
- **GIVEN** 某任务原始错误包含文件路径、原文或上游响应
- **WHEN** 管理员读取列表或详情
- **THEN** 系统 MUST 仅返回错误白名单映射，未知错误显示通用处理失败说明
- **AND** MUST NOT 返回原文件名、标题、存储路径、chunk、向量、查询、回答、引用内容或原始 error_message
- **AND** 历史已删除账号 MUST 显示为已删除账号，不能据此恢复访问权限

### Requirement: 关联阶段详情与诚实进度
`GET /api/admin/jobs/{kind}/{id}` SHALL 返回当前任务安全详情及同一上传的三阶段任务元数据；不存在返回 404 `admin_job_not_found`。详情 MUST 保留各次任务 ID 和时间，不将多次尝试拼成虚假的一次处理成功。

#### Scenario: 查看处理时间线
- **WHEN** 解析成功，但分块失败且尚未创建向量化任务
- **THEN** 详情 MUST 显示实际解析、分块状态，并将向量化展示为尚未创建
- **AND** MUST NOT 推断向量化失败或展示虚构完成百分比
- **AND** 所有阶段关联 MUST 使用实际上传/解析关联，不能仅凭所属账号关联

#### Scenario: 只读与用户资料隔离
- **WHEN** 管理员查看他人的任务
- **THEN** 页面 MUST NOT 提供正文预览、下载、跨用户重试、取消或删除入口
- **AND** 原资料 API 对该管理员读取他人资源的请求 MUST 继续返回既有不可访问语义
- **AND** 长时间 running MUST 仅提示建议检查，MUST NOT 自动改写任务状态

### Requirement: 可解释的系统诊断
`GET /api/admin/system/status` SHALL 返回 `checked_at,scope,instance_id,components[]`，包括数据库可访问性、pgvector 扩展和现有文档模型 readiness；状态为 `ok/degraded/unavailable/unknown/disabled`。接口 MUST 要求 `operations:read`，每项主动检查最多 2 秒，总截止时间 5 秒。

#### Scenario: 局部故障
- **WHEN** 认证成功后某依赖检查失败，其他组件可读取
- **THEN** 系统 MUST 返回各组件真实状态和安全失败原因，不能将检查失败替换为 ok
- **AND** 文档模型状态 MUST 标记当前进程范围，MUST NOT 冒充所有 worker 状态
- **WHEN** 认证数据库完全不可用
- **THEN** 系统 MUST 保持认证边界并返回依赖不可用错误，MUST NOT 提供匿名诊断旁路

#### Scenario: 刷新不调用外部模型
- **WHEN** 管理员刷新系统状态或总览
- **THEN** 系统 MUST NOT 自动访问模型供应商，只能显示最近显式测试及时间
- **AND** 未测试或无法检查 MUST 显示 unknown，未启用 MUST 显示 disabled
- **AND** 诊断 MUST NOT 读取向量值、写入资料或重启模型进程
