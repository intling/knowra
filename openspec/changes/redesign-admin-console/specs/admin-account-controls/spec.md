## ADDED Requirements

### Requirement: 全量账号搜索与详情
`GET /api/admin/users` SHALL 增加 `q,role,status` 查询，保留原分页契约及默认行为。q MUST 对邮箱和显示名执行大小写不敏感的字面子串匹配，最多 100 字符；组合条件 MUST 使用 AND，不能只过滤当前页。`GET /api/admin/users/{id}` SHALL 返回 `user,active_session_count,chat_limit`。全部接口 MUST 要求 `users:manage`。

q SHALL 在匹配前去除首尾空白，空值或纯空白等同未搜索；长度上限按原始查询字符串的字符数校验。列表 SHALL 保持 `(created_at ASC,id ASC)` 稳定排序、原 UserRead 字段白名单和分页结构。详情的 user SHALL 使用同一 UserRead，chat_limit SHALL 使用滚动额度快照契约；读取 SHALL NOT 修改凭据、会话、额度预留或资料。

#### Scenario: 组合筛选
- **WHEN** 管理员搜索名称并限定 member、active
- **THEN** 响应 MUST 仅含未软删除且同时满足条件的账号，总数 MUST 为匹配全量记录数
- **AND** 搜索中的百分号和下划线 MUST 按字面匹配，不能作为 SQL 通配符
- **AND** 无匹配 MUST 返回 200 与空列表；非法条件 MUST 返回有原因的 422

#### Scenario: 用户运行详情
- **WHEN** 管理员打开某有效账号详情
- **THEN** 响应 MUST 仅含账号资料、未过期未撤销会话数及额度快照
- **AND** MUST NOT 返回 token、凭据哈希、文档正文、问题、回答或资料路径
- **WHEN** 目标已删除或不存在
- **THEN** 接口 MUST 返回 404 `user_not_found` 与可读原因

### Requirement: 滚动问答额度管理
`GET /api/admin/users/{id}/chat-limit` SHALL 返回 `hourly_limit,occupied_slots,remaining,window_seconds,observed_at`；窗口为 3600 秒。`PUT` 同路径 SHALL 接受 `{hourly_limit:null或1..100000整数}`，null 表示不限额；成功返回 200 和额度快照，非法值返回说明范围的 422。不限额时 limit、占用和剩余额度 MUST 为 null。

#### Scenario: 展示占用口径
- **WHEN** 有限额账号有已成功请求和未完成预留
- **THEN** 页面 MUST 将窗口内记录展示为“已占用额度（含处理中）”，MUST NOT 称精确成功问答总数
- **AND** MUST NOT 将该表用于历史请求量、Token 用量或账单

#### Scenario: 收紧或放宽
- **GIVEN** 当前窗口已占用 3 个额度
- **WHEN** 管理员将限额改为 2
- **THEN** 修改 MUST 成功、剩余额度 MUST 为 0、已有预留 MUST 保留、后续请求 MUST 按原限额错误契约返回 429
- **WHEN** 管理员再将限额改为 5
- **THEN** 新快照剩余额度 MUST 为 2
- **AND** 失败与生成降级释放、缓存成功计次的既有规则 MUST 保留

#### Scenario: 并发切换不限额
- **WHEN** 额度新增、删除或修改与多个问答准入并发执行
- **THEN** 系统 MUST 使用同一按账号稳定的事务互斥边界，包含原来没有限额行的情形
- **AND** 修改提交前已接纳的请求 MUST 按接纳时规则继续，提交后的新准入 MUST 使用新规则
- **AND** 不限额请求 MUST NOT 追溯补记；切回有限额 MUST 保留并计算尚未过期的旧预留
- **AND** 事务锁 MUST NOT 跨越外部模型调用

### Requirement: 撤销他人会话
`POST /api/admin/users/{id}/revoke-sessions` SHALL 撤销目标全部有效会话，返回 200 `{revoked_count}`，不改变密码、角色、状态或资料。重复执行 MUST 可成功返回 0。

#### Scenario: 确认退出所有设备
- **WHEN** 管理员选择让其他账号退出所有设备
- **THEN** 页面 MUST 确认目标账号和重新登录影响，取消 MUST NOT 发起写请求
- **WHEN** 确认成功
- **THEN** 目标后续请求 MUST 需要重新认证，业务写入与成功审计 MUST 原子提交
- **AND** 页面 MUST 更新有效会话数量

#### Scenario: 自身与操作者失效
- **WHEN** 管理员调用自身的撤销会话接口
- **THEN** 系统 MUST 返回 409 `cannot_revoke_self_sessions` 并引导账户操作
- **WHEN** 操作者在提交前已被禁用或失去管理权限
- **THEN** 服务端 MUST 拒绝写入且 MUST NOT 撤销目标会话或修改额度

### Requirement: 既有账号保护继续生效
新增界面与服务 SHALL 保留至少一位有效管理员、不得禁用/删除自身、软删除保留归属、重置密码撤销会话、密钥及密码不回显的既有规则。

#### Scenario: 兼容原生命周期
- **WHEN** 使用改版后的页面或旧客户端执行用户新增、角色调整、禁用、重置密码和删除
- **THEN** 原有成功结构及 `last_admin` 等错误语义 MUST 保留
- **AND** 并发操作 MUST NOT 使有效管理员数量降为 0
