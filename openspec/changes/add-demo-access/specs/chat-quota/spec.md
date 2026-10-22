## Purpose

为共享演示账号提供由服务端统一执行的滚动小时问答额度，使基于资料的检索与引用回答可被受控试用，并让不同设备、登录会话和并发请求共享相同计数及明确的恢复时间。

## ADDED Requirements

### Requirement: 用户级滚动小时额度

系统 SHALL 对配置额度的用户限制最近 60 分钟内成功问答次数，默认没有配置的用户不受此限制。每次成功请求，包括缓存命中，均 MUST 计数，聊天线程标识不能改变额度。

#### Scenario: 三次成功后拒绝
- **WHEN** 配置为每小时 3 次的用户已成功问答 3 次后再次 POST /api/search
- **THEN** 系统 MUST 返回 429、code=chat_quota_exceeded、含限额与重试提示的中文 detail，以及正整数 Retry-After 秒数
- **AND** MUST NOT 执行新的检索、重写、Embedding 或对话调用

#### Scenario: 额度归属用户
- **WHEN** 用户更换设备、重新登录或更换 session_id，或服务进程重新启动
- **THEN** 系统 MUST 继续使用同一用户的持久化历史判断额度
- **AND** 其他用户的额度及无限制用户 MUST 不受影响

#### Scenario: 滚动恢复
- **WHEN** 一次已计数问答距当前时间达到 60 分钟
- **THEN** 该问答 MUST 不再占用额度，不必等整点或再次登录

### Requirement: 并发准入与失败释放

系统 SHALL 在调用检索和外部模型前原子预留额度，并将未完成的预留计入并发上限。失败请求 MUST 释放预留，原有检索结果、引用和降级响应结构 MUST 保持。

#### Scenario: 并发不会超额
- **WHEN** 同一用户在只有 3 个空余额度时通过多个连接同时提问
- **THEN** 系统 MUST 最多允许 3 个请求进入检索或模型阶段，其余返回带原因的 429

#### Scenario: 失败不扣次数
- **WHEN** 请求参数无效、未授权、无向量资料、外部适配器失败，或响应包含 generation_error
- **THEN** 系统 MUST 保留既有错误/降级契约，MUST NOT 留下成功次数占用

#### Scenario: 进程异常终止
- **WHEN** 未完成请求因 SIGKILL 或主机故障无法释放预留
- **THEN** 预留 MUST 在 60 分钟窗口到期后不再阻塞新的问答

### Requirement: 受保护的账号与额度初始化

系统 SHALL 提供管理员本机命令创建普通成员，并可配置正整数小时额度，密码仅从交互提示或 stdin 读取。账号、凭据与额度 MUST 原子创建，密码及凭据哈希 MUST NOT 出现在输出中。

#### Scenario: 创建受限成员
- **WHEN** 提交未占用邮箱、显示名、合规密码和 hourly-chat-limit=3
- **THEN** 系统 MUST 创建 active member、独立哈希凭据和每小时 3 次配置，且初始使用次数为零

#### Scenario: 无效输入
- **WHEN** 邮箱已占用、密码不合规或小时额度不是正整数
- **THEN** 命令 MUST 返回非零退出码并说明原因，MUST NOT 创建部分账号或改变已有用户角色/额度
