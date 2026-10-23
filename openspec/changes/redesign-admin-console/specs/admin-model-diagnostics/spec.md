## ADDED Requirements

### Requirement: 四用途生效配置概览
`GET /api/admin/models/effective` SHALL 对 chat、embedding、rerank、query_rewrite 各返回一个用途摘要，包含配置来源、启用状态、安全模型标识、profile ID、绑定版本和最近测试摘要。配置响应 SHALL 增加单调递增的 `revision`，与用途绑定版本区分。全部模型诊断接口 MUST 要求 `models:manage`。

#### Scenario: 环境来源与后台来源
- **WHEN** 某用途没有后台默认绑定
- **THEN** 页面 MUST 明确显示环境配置或未启用，MUST NOT 将其显示成后台默认
- **WHEN** 某用途已绑定后台默认
- **THEN** 页面 MUST 显示当前配置及版本，其他启用配置 MUST NOT 被误标为默认
- **AND** 响应 MUST NOT 包含任何明文/密文密钥、环境主密钥或原始环境变量集合

### Requirement: 显式且不改变生产配置的测试
`POST /api/admin/models/{id}/test` SHALL 接受 `{expected_revision}`，仅访问该已保存配置，使用固定非私有样例验证用途所需协议。测试 MUST NOT 激活配置、切换默认、触发知识库检索或自动重建索引；禁用配置也可被显式测试。

#### Scenario: 测试执行与结果
- **WHEN** 管理员确认测试一个版本匹配的已保存配置
- **THEN** 系统 MUST 使用该版本快照执行一次有界调用，返回 200 与 `probe_id,status,code,detail,latency_ms,checked_at,config_revision,is_current`
- **AND** 页面 MUST 说明少量测试内容可能产生费用
- **AND** Embedding MUST 校验返回维度，重排 MUST 校验结果结构，对话与改写 MUST 限制输出
- **AND** 测试通过 MUST NOT 表述为检索质量或带引用回答质量已合格

#### Scenario: 未执行的测试
- **WHEN** 配置不存在、版本不匹配或无法解密密钥
- **THEN** 系统 MUST 分别返回 404 配置不存在原因、409 `model_revision_conflict` 或 503 `model_secret_unavailable`
- **AND** MUST NOT 调用外部服务或回退到环境配置
- **WHEN** 请求包含任意 URL、临时密钥或自定义模型请求体
- **THEN** 系统 MUST 以不回显秘密的 422 拒绝

### Requirement: 有界外部访问与跨进程限流
测试 SHALL 具有默认 10 秒、最大 30 秒的总截止时间、零重试、每配置默认 30 秒冷却及全局默认 2 个并发，跨同一数据库的 worker 一致。测试 MUST 允许既有本机和私网模型地址，但禁止云元数据/链路本地目标和重定向，且校验 MUST 约束实际连接。

#### Scenario: 超时与服务错误
- **WHEN** 上游超时、拒绝鉴权、无法连接或响应格式/维度错误
- **THEN** 有效执行结果 MUST 为 HTTP 200 `status:failed`，code 分别为 `model_test_timeout`、`model_test_auth_failed`、`model_test_unreachable` 或 `model_test_invalid_response`
- **AND** detail MUST 为安全说明，MUST NOT 包含原始响应、密钥、Authorization 或内部堆栈
- **AND** 客户端与并发名额 MUST 在截止时间及清理宽限内释放

#### Scenario: 并发和冷却
- **WHEN** 多个 worker 同时测试相同配置，或总在途测试达到上限
- **THEN** 超出准入的请求 MUST 返回 429 `model_test_rate_limited` 和正数 `Retry-After`
- **AND** 网络调用 MUST NOT 持有准入事务或数据库行锁

#### Scenario: 关闭或强杀
- **WHEN** 应用开始关闭
- **THEN** 新测试 MUST 被拒绝，在途测试 MUST 在截止时间和 shutdown 宽限内完成或中断并释放客户端
- **WHEN** 进程被强杀而未写入终态
- **THEN** 租约过期的 running 记录 MUST 作为 interrupted/unknown，MUST NOT 持续占用并发名额或标记为成功

### Requirement: 测试结果与配置版本绑定
最近测试 SHALL 记录版本与检查时间，仅在版本仍一致且检查距当前不超过 15 分钟时作为当前参考结果；过期 MUST 明确展示。测试结果和结果审计 MUST 在完成事务中一起保存。

#### Scenario: 测试期间编辑配置
- **WHEN** 测试进行中配置被编辑或删除
- **THEN** 返回/保存结果 MUST 仍关联所测旧版本，且 `is_current` MUST 为 false
- **AND** 页面 MUST NOT 用该结果证明当前配置可用

#### Scenario: 保留既有向量保护
- **WHEN** 管理员测试或切换 Embedding 配置
- **THEN** 测试 MUST NOT 绕开既有默认切换、索引空间兼容或在途任务协调规则
- **AND** `embedding_index_conflict` 等拒绝 MUST 保持原默认和索引不变
