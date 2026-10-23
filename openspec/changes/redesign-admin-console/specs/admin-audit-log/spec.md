## ADDED Requirements

### Requirement: 管理操作持久化
系统 SHALL 持久化账号新增、角色/状态变更、重置密码、软删除、额度调整、会话撤销、模型配置及默认变更、模型测试结果。事件 MUST 含 `id,actor_user_id,action,resource_type,resource_id,result,changes_json,error_code,trace_id,created_at`，result 为 success/denied/failed，时间为 UTC。

action SHALL 使用固定枚举 `user.create/update/reset_password/delete/chat_limit.update/sessions.revoke`、`model.create/update/activate/deactivate/delete/test`；resource_type SHALL 为 user/model。账号邮箱、用户显示名、配置显示名及完整地址 MUST NOT 出现在 changes_json。状态变化 SHALL 使用字段级 `{before,after}`，只记录实际变化；密钥和地址仅允许布尔标记。具体动作字段白名单以 design 第 9 节为契约。

#### Scenario: 追溯管理变更
- **WHEN** 管理员完成模型默认切换或收紧用户额度
- **THEN** 审计 MUST 能定位操作者、对象、动作、时间、结果、trace ID 和安全前后值
- **AND** 软删除对象后事件 MUST 保留原资源 ID，不能级联删除历史

### Requirement: 审计白名单与秘密隔离
审计 SHALL 按动作使用字段白名单，仅保留安全状态变化；密码重置只记动作，密钥变化只记布尔标记，地址变化只记 `endpoint_changed`。查询 MUST NOT 将业务日志流原样提供给后台。

#### Scenario: 秘密和私有内容不入库
- **WHEN** 管理员设置密码、录入 API Key 或测试上游服务
- **THEN** 审计与诊断结果 MUST NOT 保存密码及哈希、密钥明密文、会话材料、原始请求/响应或任意业务资料内容
- **AND** 查询响应 MUST 经过同一白名单投影，MUST NOT 暴露文件名、路径、问题、回答或向量

### Requirement: 写操作与成功事件原子提交
账号、额度、会话及模型写操作 SHALL 与成功审计在同一业务事务提交；审计插入失败 MUST 回滚业务操作。已认证管理操作的失败/拒绝 SHALL 在回滚后尝试独立记录，不能将失败事务错误地标为成功。

#### Scenario: 审计不可写
- **WHEN** 管理员请求写入有效业务变更，但审计插入失败
- **THEN** 接口 MUST 返回 503 `admin_audit_unavailable` 与明确原因
- **AND** 用户状态、额度、会话或模型默认 MUST 保持修改前状态

#### Scenario: 拒绝与重复提交
- **WHEN** 操作因最后管理员保护、版本冲突或其他业务约束被拒绝
- **THEN** 系统 MUST 尝试记录 denied/failed 及安全错误码，不产生成功事件
- **AND** 失败审计也不可写时 MUST 以项目结构化 logger 记录安全字段并保留原业务错误
- **AND** 4xx 业务拒绝 SHALL 记录 denied，5xx 依赖失败 SHALL 记录 failed，changes_json 为空，error_code 为服务端稳定业务码
- **AND** 创建失败 SHALL 使用本次尝试预分配的资源 UUID，不将冲突账号当作新增资源
- **WHEN** 同一请求在事务内部重试
- **THEN** 系统 MUST NOT 为同一已提交变更生成多份成功审计
- **AND** 相同 trace ID 的两个独立成功操作 SHALL 分别留痕，trace ID 不充当业务幂等键

### Requirement: 审计查询与权限
`GET /api/admin/audit-events` SHALL 要求 `audit:read`，支持 `from,to,actor_user_id,action,result,trace_id,offset,limit`，默认最近 7 天、单次最长 31 天，按 `(created_at DESC,id DESC)` 排序并返回 `{items,total,offset,limit}`。

#### Scenario: 条件查询与空状态
- **WHEN** 管理员按操作者、失败结果和时间查询
- **THEN** 接口 MUST 返回全量匹配条件的分页及总数
- **AND** 无记录 MUST 返回 200 空列表，非法枚举或反向时间 MUST 返回有原因的 422

#### Scenario: 无权限和不可变台账
- **WHEN** 成员、只读用户或未登录访问者读取审计
- **THEN** 服务端 MUST 分别按认证状态返回 403 或 401，不返回事件
- **AND** 首期管理界面及 API MUST NOT 提供编辑、删除、导出或任意日志文件读取功能
