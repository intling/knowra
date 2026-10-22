## Purpose

在既有邮箱密码认证、三类固定角色和管理员用户列表的基础上，补齐管理员创建账号、重置他人密码和软删除能力，保持凭据安全、会话可撤销与私有资料归属可追溯。

## ADDED Requirements

### Requirement: 管理员创建用户
系统 SHALL 提供 `POST /api/admin/users`，接收 `email`、`display_name`、`password`、`role` 和可选 `status`，成功返回 201 及公开用户结构；角色默认 `member`、状态默认 `active`。

#### Scenario: 创建并登录
- **WHEN** 管理员提交有效账号，角色为 `admin`、`member` 或 `viewer`
- **THEN** 系统 MUST 规范化邮箱和名称，保存独立哈希凭据，并返回账号角色及权限
- **AND** 新账号 MUST 可通过普通登录入口登录，创建者会话 MUST 保持原管理员身份

#### Scenario: 输入无效或邮箱重复
- **WHEN** 邮箱、名称、密码、角色或状态不符合现有规则
- **THEN** 系统 MUST 返回 422 和具体原因，且 MUST NOT 创建账号或凭据
- **WHEN** 规范化邮箱已被账号占用，包括已软删除账号
- **THEN** 系统 MUST 返回 409、`email_conflict` 和具体原因，MUST NOT 认领、恢复或修改原账号

### Requirement: 管理员重置他人密码
系统 SHALL 提供 `POST /api/admin/users/{id}/reset-password`，接收 `new_password`，仅用于重置其他未删除账号的密码，成功返回 204。

#### Scenario: 重置密码与会话撤销
- **WHEN** 管理员为目标账号提交符合现有策略的新密码
- **THEN** 系统 MUST 更新哈希并撤销目标账号的全部会话，旧密码 MUST 失效
- **AND** 启用中的目标账号 MUST 可以用新密码登录，禁用中的目标账号 MUST 保持禁用
- **AND** 操作者的会话 MUST 保持有效

#### Scenario: 失败时保持原凭据
- **WHEN** 新密码不符合策略
- **THEN** 系统 MUST 返回 422、`weak_password` 及具体原因，原凭据与目标会话 MUST 保持有效
- **WHEN** 目标为当前登录账号
- **THEN** 系统 MUST 返回 409、`cannot_reset_self` 并指引使用账户设置
- **WHEN** 目标不存在或已删除
- **THEN** 系统 MUST 返回 404、`user_not_found` 及具体原因

### Requirement: 管理员软删除用户
系统 SHALL 提供 `DELETE /api/admin/users/{id}`，成功返回 204，设置 `deleted_at`、禁用账号并撤销全部会话；MUST NOT 物理删除用户、凭据或历史资料。

#### Scenario: 删除后的访问
- **WHEN** 管理员成功删除一个账号
- **THEN** 该账号 MUST 从普通用户列表排除，其旧会话 MUST 返回 401，新登录 MUST 被拒绝
- **AND** 该账号的上传、文档、分块、向量及全部归属外键 MUST 保持原值
- **AND** 管理员 MUST NOT 因删除账号而获得这些资料的访问权

#### Scenario: 删除保护
- **WHEN** 管理员尝试删除自己
- **THEN** 系统 MUST 返回 409、`cannot_delete_self` 与具体原因
- **WHEN** 删除与并发角色或状态修改会移除最后一个有效管理员
- **THEN** 系统 MUST 在一致的并发保护下拒绝操作并保留有效管理员
- **WHEN** 目标不存在或已删除
- **THEN** 系统 MUST 返回 404、`user_not_found` 与具体原因

### Requirement: 生命周期权限与秘密边界
所有新增用户管理接口 SHALL 使用既有 `users:manage` 权限、可信来源检查和统一错误格式；响应、校验错误及日志 MUST NOT 包含密码、密码哈希、Cookie 或令牌。

#### Scenario: 未授权与跨站调用
- **WHEN** 匿名、成员、只读用户或不可信来源调用写接口
- **THEN** 系统 MUST 分别返回 401、403 或 403 并给出具体原因
- **AND** 用户、凭据、会话和资料 MUST 保持原状

#### Scenario: 秘密不回显
- **WHEN** 账号创建或重置成功、失败或触发校验错误
- **THEN** 响应和业务日志 MUST NOT 出现提交的密码、密码哈希或会话令牌
