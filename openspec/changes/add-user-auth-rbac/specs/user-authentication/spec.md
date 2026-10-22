## ADDED Requirements

### Requirement: 邮箱密码注册
系统 SHALL 提供 `POST /api/auth/register`，以规范化邮箱、显示名和符合策略的密码创建普通成员账号，并在成功后自动建立登录会话。

#### Scenario: 注册成功并自动登录
- **WHEN** 匿名用户提交未注册的邮箱 ` Foo@Example.com `、合法显示名和合规密码
- **THEN** API MUST 返回 201 和 `UserRead`，`email` MUST 为 `foo@example.com`，`role` MUST 为 `member`
- **AND** 响应 MUST 设置 `knowra_session` Cookie，属性包含 `HttpOnly`、`SameSite=Lax`、`Path=/api` 和 `Max-Age`
- **AND** 随后使用该 Cookie 请求 `GET /api/users/me` MUST 返回同一用户

#### Scenario: 邮箱重复
- **WHEN** 提交的邮箱在大小写和首尾空白规范化后与已有账号相同
- **THEN** API MUST 返回 409、`code=email_taken` 和可读原因，且 MUST NOT 创建账号

#### Scenario: 输入不合法
- **WHEN** 邮箱格式错误、显示名为空或超过 100 字符、密码少于 10 或多于 128 字符、缺少字母或数字、或等于邮箱及其本地部分
- **THEN** API MUST 返回 422，`code` 分别为 `invalid_email`、`invalid_display_name` 或 `weak_password`，`detail` MUST 说明未满足的具体规则
- **AND** MUST NOT 创建账号或会话

### Requirement: 登录与防爆破
系统 SHALL 提供 `POST /api/auth/login`，校验邮箱和密码后签发新会话，并限制同一邮箱的连续失败次数。

#### Scenario: 登录成功
- **WHEN** 有效用户提交正确邮箱（大小写不敏感）和密码
- **THEN** API MUST 返回 200 和 `UserRead`，并设置新的会话 Cookie
- **AND** 若请求已携带旧会话 Cookie，旧会话 MUST 被撤销

#### Scenario: 凭据错误不暴露账号是否存在
- **WHEN** 邮箱不存在、账号没有凭据或密码错误
- **THEN** API MUST 返回相同的 401、`code=invalid_credentials` 和相同 `detail`

#### Scenario: 禁用账号
- **WHEN** 已禁用账号提交正确密码
- **THEN** API MUST 返回 403、`code=account_disabled`，且 MUST NOT 创建会话

#### Scenario: 连续失败触发限流
- **WHEN** 同一邮箱在窗口期内失败达到配置次数（默认 15 分钟内 5 次）
- **THEN** 窗口结束前的登录 MUST 返回 429、`code=too_many_attempts` 和 `Retry-After` 秒数，即使密码正确也 MUST NOT 登录
- **AND** 窗口结束后 MUST 恢复正常校验；登录成功后失败计数 MUST 清零

### Requirement: 可撤销的服务端会话
系统 SHALL 使用数据库保存的 opaque 会话识别用户，库中只保存令牌哈希，并支持过期和撤销。

#### Scenario: 令牌只存哈希
- **WHEN** 会话被创建
- **THEN** 数据库 MUST 只保存令牌的 SHA-256 哈希，MUST NOT 保存 Cookie 原文

#### Scenario: 退出
- **WHEN** 已登录用户请求 `POST /api/auth/logout`
- **THEN** API MUST 返回 204、撤销当前会话并清除 Cookie
- **AND** 继续使用旧 Cookie 访问私有接口 MUST 返回 401
- **WHEN** 未携带会话的请求调用退出
- **THEN** API MUST 仍返回 204

#### Scenario: 会话过期
- **WHEN** 会话超过绝对有效期
- **THEN** 任何私有接口 MUST 返回 401、`code=auth_required` 和重新登录提示

### Requirement: CSRF 与跨域防护
系统 SHALL 对所有改变状态的 API 请求校验来源，并禁止不安全的跨域与 Cookie 配置。

#### Scenario: 不可信来源
- **WHEN** `POST`、`PUT`、`PATCH` 或 `DELETE` 请求携带不在 `BACKEND_CORS_ORIGINS` 中的 `Origin`，或没有 `Origin` 但 `Sec-Fetch-Site` 为 `cross-site`
- **THEN** API MUST 返回 403、`code=csrf_origin_rejected`，且 MUST NOT 执行登录、注册或任何写操作

#### Scenario: 可信来源与非浏览器客户端
- **WHEN** 请求的 `Origin` 属于白名单，或请求既没有 `Origin` 也没有 `Sec-Fetch-Site`
- **THEN** 来源校验 MUST 放行

#### Scenario: 不安全配置
- **WHEN** `BACKEND_CORS_ORIGINS` 包含 `*`，或 `APP_ENV` 为生产环境而 `AUTH_COOKIE_SECURE=false`
- **THEN** 配置加载 MUST 失败并给出明确原因

### Requirement: 个人资料与密码管理
已登录用户 SHALL 能修改自己的显示名和密码。

#### Scenario: 修改显示名
- **WHEN** 已登录用户提交 `PATCH /api/users/me` 和合法 `display_name`
- **THEN** API MUST 返回 200 和更新后的 `UserRead`
- **AND** 请求体中的 `role`、`status`、`email` 等字段 MUST 被忽略

#### Scenario: 修改密码
- **WHEN** 用户提交正确的当前密码和合规新密码
- **THEN** API MUST 返回 204、撤销该用户全部会话并清除 Cookie
- **AND** 旧密码 MUST 无法登录，新密码 MUST 可以登录

#### Scenario: 当前密码错误
- **WHEN** 用户提交错误的当前密码
- **THEN** API MUST 返回 400、`code=current_password_incorrect`，MUST NOT 返回 401，且会话保持有效

### Requirement: 密码安全存储与日志
系统 SHALL 只保存自适应密码哈希，且响应与日志 MUST NOT 暴露认证秘密。

#### Scenario: 请求校验失败不回显秘密
- **WHEN** 注册、登录或改密请求缺少字段、字段类型错误或 JSON 无法解析
- **THEN** 422 响应 MUST 保留可定位错误的 `detail` 列表，但 MUST NOT 回显输入值、完整请求体或密码

#### Scenario: 哈希存储
- **WHEN** 账号设置密码
- **THEN** 凭据 MUST 以 argon2id 哈希保存在独立凭据表

#### Scenario: 秘密不外泄
- **WHEN** 完成注册、登录、改密和退出流程
- **THEN** 任何 API 响应和日志 MUST NOT 包含明文密码、会话令牌或令牌哈希
