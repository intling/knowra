## REMOVED Requirements

### Requirement: 当前用户解析
**Reason**: 默认用户解析被真实会话认证取代，禁止匿名回退；原场景不能继续保留。
**Migration**: 使用新增「会话当前用户解析」；旧默认用户需通过 CLI 显式认领后登录。

### Requirement: 当前用户 API
**Reason**: 原接口契约假定匿名默认用户且不提供注册能力，现改为认证账号契约。
**Migration**: 使用新增「已认证当前用户 API」及 `user-authentication` 注册接口。

### Requirement: 前端当前用户状态
**Reason**: 原规范禁止认证入口，与此次登录、注册和账户管理流程冲突。
**Migration**: 使用新增「前端认证用户状态」和 `user-account-ui`；私有状态绑定真实用户。

## ADDED Requirements

### Requirement: 会话当前用户解析
系统 SHALL 通过真实有效的服务端会话统一解析当前用户，并在每次业务请求中校验会话有效期、撤销状态、用户状态和软删除状态。系统 MUST NOT 回退为默认用户或匿名用户。

#### Scenario: 解析已登录用户
- **WHEN** 请求携带有效会话，关联用户为 `active` 且 `deleted_at` 为空
- **THEN** 当前用户解析 MUST 返回该会话关联用户
- **AND** 后端 MUST 根据数据库最新角色判定权限

#### Scenario: 会话缺失或不可用
- **WHEN** 会话缺失、伪造、过期、被撤销或关联用户不可用
- **THEN** 当前用户解析 MUST 返回 401 和明确的重新登录提示
- **AND** 即使默认用户存在也 MUST NOT 返回默认用户

### Requirement: 已认证当前用户 API
系统 SHALL 通过 `GET /api/users/me` 返回已认证用户，并仅暴露公开账户字段。

#### Scenario: 获取当前用户成功
- **WHEN** 已登录用户请求 `GET /api/users/me`
- **THEN** API MUST 返回 200
- **AND** 响应 MUST 保留 `id`、`display_name`、`email`、`avatar_url`、`status`、`deleted_at`、`created_at`、`updated_at`，增加 `role` 和 `permissions`
- **AND** 响应 MUST NOT 包含密码哈希、会话令牌或 CSRF 密钥

#### Scenario: 当前用户不可用
- **WHEN** 请求不能解析出有效已登录用户
- **THEN** API MUST 返回 401
- **AND** 响应 MUST 包含明确的重新登录提示

#### Scenario: 注册使用认证 API
- **WHEN** 客户端创建普通账号
- **THEN** 客户端 MUST 使用本变更新增的认证注册接口
- **AND** 系统 MUST NOT 将管理员用户管理接口作为公开注册入口

### Requirement: 前端认证用户状态
前端 SHALL 封装当前用户读取，区分加载、已认证、未认证、请求错误，并以当前用户作为所有私有界面状态的归属。

#### Scenario: 前端获取当前用户
- **WHEN** 前端调用 `getCurrentUser()`
- **THEN** 前端 MUST 请求 `GET /api/users/me`
- **AND** 前端 MUST NOT 在业务代码中硬编码后端主机地址

#### Scenario: 前端用户加载成功
- **WHEN** `GET /api/users/me` 返回已认证用户
- **THEN** user store MUST 保存当前用户及其角色和权限
- **AND** 前端 MUST 绑定该用户的对话空间

#### Scenario: 前端用户加载失败
- **WHEN** `GET /api/users/me` 返回 401
- **THEN** 前端 MUST 清除旧用户和私有内存状态，并引导登录
- **WHEN** 发生网络或服务错误
- **THEN** 前端 MUST 展示可重试错误，且 MUST NOT 展示上个用户的资料

#### Scenario: 提供认证与账户入口
- **WHEN** 用户访问应用
- **THEN** 前端 MUST 提供登录、注册、退出和个人账户管理入口
- **AND** 管理员 MUST 能访问用户管理入口
