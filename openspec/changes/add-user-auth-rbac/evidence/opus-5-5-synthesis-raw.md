# knowra 用户体系架构设计（唯一推荐方案）

## 0. 总体原则

- 认证方式为服务端会话。浏览器只持有 HttpOnly Cookie，令牌在库中只存 SHA-256 哈希。
- 每个请求都重新加载用户、角色和状态，因此角色变更、禁用操作立即生效。
- 资源归属一律以 `owner_user_id == current_user.id` 为准。访问不属于自己的资源返回 **404**，不暴露资源是否存在。
- 管理员权限只覆盖账号管理，不能读取他人资料。

## 1. API 契约

### 错误格式

- 业务错误统一为 `{"detail": "中文可读原因", "code": "<机器码>"}`，由自定义 `AppError` 的异常处理器输出。
- 422 校验错误保持 FastAPI 默认格式。

| code | HTTP 状态码 | 默认 detail |
|---|---|---|
| auth_required | 401 | 请先登录 |
| invalid_credentials | 401 | 邮箱或密码错误 |
| account_disabled | 403 | 账号已被禁用 |
| csrf_failed | 403 | 安全校验失败，请刷新后重试 |
| forbidden | 403 | 当前账号无权执行此操作 |
| registration_closed | 403 | 暂未开放注册 |
| email_taken | 409 | 该邮箱已注册 |
| last_admin | 409 | 不能移除最后一位有效管理员 |
| self_disable | 400 | 不能禁用当前登录账号 |
| invalid_password | 400 | 当前密码不正确 |
| weak_password | 422 | 具体策略原因 |
| rate_limited | 429 | 尝试过于频繁，请稍后再试 |
| not_found | 404 | 资源不存在 |

- 429 响应必须带 `Retry-After` 头（单位：秒）。

### UserRead

```json
{"id","display_name","email","avatar_url","role":"admin|member|viewer",
 "status":"active|disabled","permissions":["..."],"created_at","last_login_at"}
```

- 响应中不得包含 password_hash 和任何令牌。

### 接口清单

除 GET 外，所有方法都需要 CSRF 校验。

| 方法 & 路径 | 请求 | 成功响应 |
|---|---|---|
| GET `/api/auth/csrf` | — | 200 `{"csrf_token": str}`，同时 Set-Cookie `knowra_csrf` |
| POST `/api/auth/register` | `{display_name(1–100), email, password}` | 201 `{"user": UserRead, "csrf_token": str}`，**自动登录** |
| POST `/api/auth/login` | `{email, password}` | 200 `{"user": UserRead, "csrf_token": str}` |
| POST `/api/auth/logout` | — | 204，幂等；撤销当前会话并清空两个 Cookie |
| GET `/api/users/me` | — | 200 UserRead / 401 |
| PATCH `/api/users/me` | `{display_name}` | 200 UserRead |
| POST `/api/users/me/password` | `{current_password, new_password}` | 204；撤销该用户**全部**会话并清 Cookie |
| GET `/api/admin/users?page=1&page_size=20&q=&role=&status=` | page_size 取值 1–100 | 200 `{"items":[UserRead],"total","page","page_size"}` |
| PATCH `/api/admin/users/{user_id}` | `{role?, status?}`，至少一项 | 200 UserRead；禁用时撤销目标用户全部会话 |

补充规则：

- **邮箱**：服务端统一 `strip().lower()`。
- **登录**：
  - 邮箱不存在、`password_hash` 为空、密码错误，一律返回 `invalid_credentials`。
  - 密码正确但账号被禁用，返回 `account_disabled`。
  - 每次登录都轮换会话：若旧 Cookie 存在，先撤销旧会话；同时轮换 CSRF 令牌。
- **既有业务接口**：files、parse、chunk、embedding、search、统计接口全部挂上认证依赖。`GET /users/me` 不再返回 503。

## 2. Cookie、CSRF、会话表与 User 字段

### Cookie

| Cookie | 属性 | 内容 |
|---|---|---|
| `knowra_session` | HttpOnly、SameSite=Lax、Path=/、Secure=`AUTH_COOKIE_SECURE` | `secrets.token_urlsafe(32)` 生成的令牌 |
| `knowra_csrf` | 非 HttpOnly，其余同上 | CSRF 令牌 |

### CSRF

- 采用双提交：POST/PUT/PATCH/DELETE 请求必须携带头 `X-CSRF-Token`，其值与 `knowra_csrf` Cookie 做 `hmac.compare_digest` 恒定时间比较。
- 若请求带 `Origin`，该值必须属于 `AUTH_TRUSTED_ORIGINS`，否则返回 `csrf_failed`。
- 登录和注册同样需要 CSRF 校验：前端先调用 `/auth/csrf` 完成 bootstrap。

### CORS

- 设置 `allow_credentials=True`，来源使用显式白名单。
- 配置为 `*` 时启动直接报错。
- `allow_headers` 包含 `Content-Type`、`X-CSRF-Token`、`X-Trace-ID`。

### `user_sessions` 表

| 字段 | 定义 |
|---|---|
| id | UUID 主键 |
| user_id | FK users.id，带索引 |
| token_hash | CHAR(64)，唯一 |
| created_at / expires_at / last_seen_at | timestamptz |
| revoked_at | 可空 |
| user_agent | VARCHAR(255) |
| ip_address | VARCHAR(64) |

会话有效需同时满足以下条件，否则返回 401 并清除 Cookie：

- 未撤销，且 `now < expires_at`；绝对有效期 `AUTH_SESSION_TTL_HOURS=336`。
- `now - last_seen_at < AUTH_SESSION_IDLE_HOURS=72`。
- 用户为 active 且 `deleted_at` 为空。

`last_seen_at` 最多每 5 分钟写库一次。

### User 新增字段

| 字段 | 定义 | 说明 |
|---|---|---|
| password_hash | VARCHAR(255)，可空 | 为空表示不可登录 |
| role | VARCHAR(16)，非空，server_default `'member'` | CHECK 约束取值 |
| last_login_at | timestamptz，可空 | — |
| password_changed_at | timestamptz，可空 | — |

另新增唯一函数索引 `uq_users_email_lower ON lower(email)`。

## 3. 角色与权限

| 权限 | admin | member | viewer |
|---|---|---|---|
| `documents:read`（自己的资料、统计） | ✓ | ✓ | ✓ |
| `documents:write`（上传、解析、重分块、重向量化、删除） | ✓ | ✓ | ✗ |
| `search:query` | ✓ | ✓ | ✓ |
| `account:manage_self` | ✓ | ✓ | ✓ |
| `users:manage` | ✓ | ✗ | ✗ |

- 依赖写法：`require_permission("documents:write")`。权限集来自代码常量 `ROLE_PERMISSIONS`，不建库表。
- **允许管理员自降级**，前提是降级后仍有至少一位“active、未删除、admin”的用户。
- **最后管理员保护**：凡是会使有效管理员数变为 0 的角色变更或禁用操作，一律返回 409 `last_admin`。
  - 校验在事务内执行，对现有 admin 行使用 `SELECT … FOR UPDATE`，防止并发操作绕过。
- **禁止禁用自己**，返回 400 `self_disable`。

## 4. 密码与限流

### 密码策略

- 长度 10–128 个字符。
- 至少包含 1 个字母和 1 个数字。
- 不得等于邮箱，不得为纯空白。
- 前后端使用同一规则；前端只做预校验，以后端为准。

### 哈希

- 使用 `argon2-cffi` 的 Argon2id，参数为 time_cost=3、memory_cost=65536、parallelism=4。
- 登录成功时若 `check_needs_rehash` 为真，则重新哈希。
- 邮箱不存在时，对固定 dummy hash 执行一次 verify，使响应耗时一致。

### 限流

由 `AuthRateLimiter` 实现：进程内滑动窗口，可注入时钟。所有阈值均可通过环境变量配置。

| 场景 | 阈值 |
|---|---|
| 登录失败（按邮箱） | 15 分钟内 5 次失败，锁定至窗口结束；成功后清零 |
| 登录尝试（按 IP） | 5 分钟内 20 次 |
| 注册（按 IP） | 1 小时内 5 次 |
| 改密失败（按用户） | 15 分钟内 5 次 |

- 超限返回 429 `rate_limited`，并带 `Retry-After`。
- README 需注明：多 worker 部署时计数按进程独立；限流接口可替换为共享存储实现。

## 5. CLI 与默认用户认领

模块 `backend/app/cli.py`，基于 argparse，调用方式为 `uv run python -m app.cli <cmd>`。

| 命令 | 行为 |
|---|---|
| `create-admin --email E --display-name N` | 密码通过 getpass 两次输入，或读取 `KNOWRA_ADMIN_PASSWORD`；邮箱已存在时退出码 1。加 `--promote-existing` 则把已存在账号升为 admin，不改其密码。 |
| `reset-password --email E` | 设置新密码并撤销该用户全部会话。 |
| `claim-default-user --to-email E [--dry-run] --confirm` | 见下文。 |

`claim-default-user` 的规则：

- 在单事务内，把所有资源表（files、parses、chunks、embeddings、embedding jobs 等所有含 `owner_user_id` 的表）中 `owner_user_id == DEFAULT_USER_ID` 的行改为目标用户。
- 然后把默认用户的 status 设为 `disabled`，用户记录保留，以维持历史外键。
- 不带 `--confirm` 时只输出各表的计数。命令幂等，重复执行迁移 0 行。
- 目标用户必须为 active。

`claim-default-user` 的安全约束：

- 注册流程永不分配 admin，也永不关联默认用户的资料。
- `DEFAULT_USER_ID` 的 password_hash 为空，因此不可登录。
- `services/users.get_current_user(session)` 被删除，替换为 `get_current_user(request, session)` 依赖。

## 6. 搜索、重写与缓存隔离

- **SearchService**：构造参数新增必填 `owner_user_id: UUID`。`total_searched` 统计和向量查询都加 `owner_user_id` 过滤以及有效文档条件。
  - 当前用户没有任何向量时返回 404，即使其他用户有数据也一样。
- **指纹**：`compute_fingerprint(session, owner_user_id)` 只聚合该用户的 embedding 数量和该用户成功 job 的 `MAX(updated_at)`。
- **全局指纹的并发问题**：现有的 `update_fingerprint()` 修改单例状态，请求 A 和 B 之间会互相覆盖。处理方式如下：
  - 删除路由中所有 `update_fingerprint` 调用。
  - 指纹作为**不可变参数**逐请求传入：`service.search(..., kb_fingerprint=fp)` → `query_rewriter.rewrite(..., user_id, kb_fingerprint)`。
  - CacheManager 的读写接口显式接收 namespace。
- **缓存键**：
  - L1 键：`(user_id, kb_fingerprint, f"{user_id}:{session_id}", normalized_query, top_k)`。客户端传来的 session_id 一律加用户前缀。
  - L2 语义缓存：候选只在 `namespace=(user_id, kb_fingerprint)` 内比较。
  - 搜索响应缓存使用同样的命名空间。
- **失效接口**：`invalidate_all_search_caches(user_id)` 只清除该用户的命名空间。指纹已包含在键中，即使漏调失效，也不会命中过期数据。
- **审计日志**：记录 `user_id`，不记录密码和令牌。

## 7. 前端

### 新增文件（最小集合）

- `src/api/auth.ts`
- `src/router/guards.ts`
- `src/views/LoginView.vue`
- `src/views/RegisterView.vue`
- `src/views/AccountView.vue`
- `src/views/AdminUsersView.vue`

### 修改文件

- **`api/client.ts`**：
  - 新增 `ApiError{status, code, detail}`，以及 `apiRequest`、`apiPostJson`、`apiPatchJson`、`apiDelete`。
  - 统一设置 `credentials: "same-origin"`。非 GET 请求自动附带 `X-CSRF-Token`；收到 `csrf_failed` 时重新获取 CSRF 令牌并重试一次。
  - 非 `/auth/*` 请求返回 401 时，调用 `setUnauthorizedHandler` 注册的回调。
  - search、parse、rechunk、reembed 原有的独立 fetch 全部迁到 client。
- **`stores/user.ts`**：
  - state：`status: "unknown"|"authenticated"|"anonymous"`、`currentUser`、`identityEpoch`。
  - actions：`ensureSession()`（单飞）、`login`、`register`、`logout`、`updateProfile`、`changePassword`、`handleUnauthorized()`、`can(perm)`。
- **`router/index.ts`**：
  - `/login`、`/register` 设 `meta.guestOnly`。
  - `/`、`/verify`、`/account` 设 `requiresAuth`。
  - `/admin/users` 设 `requiresAuth` 加 `permission: "users:manage"`。

### 路由守卫

- `beforeEach` 先 `await ensureSession()`。App 在 `status === "unknown"` 期间不渲染 RouterView，避免闪现旧账号内容。
- 匿名访问私有页面时，跳转 `/login?redirect=<path>`。
- 已登录用户访问 guestOnly 页面时，跳转 `/`。
- 无权限访问 `/admin/users` 时照常进入该页，但页面显示“权限不足”面板，且不请求用户列表。

### `safeRedirect(raw)`

以下任一情况返回 `/`：

- 不以单个 `/` 开头；
- 以 `//` 开头；
- 任意位置包含 `\`；
- 包含控制字符；
- `new URL(raw, location.origin).origin` 与当前 origin 不一致。

### 身份切换与隔离

- **清理时机**：退出、401、跨标签页登出、改密成功时，执行以下动作：
  - `identityEpoch++`；
  - 中止所有在途请求（在 client 内维护 AbortController 注册表）；
  - 对 chat、documents、verification store 执行 `$reset`；
  - 跳转 `/login`。
- **在途响应**：各 store 在 await 之前记录 epoch，响应返回时若 epoch 已变化则丢弃结果。
- **对话存储**：
  - 键改为 `knowra:chat:v2:<userId>`，由 `chat.bindUser(id|null)` 加载或清空。
  - 旧键 `knowra:chat` 保持原样，既不读取也不导入。
- **跨标签页**：使用 `BroadcastChannel("knowra-auth")` 广播 `{type: "logout"}`。不支持 BroadcastChannel 时退回监听 `storage` 事件。
- **只读用户**：上传、解析、重分块、重向量化按钮设为 disabled，并附说明“只读账号不能上传或处理资料”。
- **侧栏**：新增账户入口，显示显示名和角色；管理员额外显示“用户管理”。
- **表单可访问性**：
  - 表单使用 `autocomplete`：email、current-password、new-password。
  - 错误提示使用 `role="alert"`，aria ID 使用 `uniqueId()` 生成。
  - 密码不写入日志或任何持久存储。
  - 登录失败后保留邮箱、清空密码。

## 8. 迁移、配置与 TDD 测试矩阵

### 迁移

只新增一个 revision `add_user_auth_rbac`，内容依次为：

1. 将现有 email 统一转为小写。若存在 lower 后重复的邮箱，迁移以明确的报错信息中止。
2. 为 users 添加 4 个新字段、role 的 CHECK 约束，以及 lower(email) 唯一索引。
3. 创建 `user_sessions` 表及其索引，包括 `expires_at` 索引。
4. 不修改默认用户的资源行。

downgrade 逆序删除上述结构。不改写任何历史迁移。

### 配置

在 `.env.example` 中新增：

- `AUTH_COOKIE_SECURE=false`
- `AUTH_SESSION_TTL_HOURS`、`AUTH_SESSION_IDLE_HOURS`
- `AUTH_REGISTRATION_ENABLED=true`
- `AUTH_TRUSTED_ORIGINS`
- `AUTH_LOGIN_MAX_FAILURES=5`、`AUTH_LOGIN_WINDOW_SECONDS=900`、`AUTH_LOGIN_IP_MAX=20`、`AUTH_LOGIN_IP_WINDOW_SECONDS=300`
- `AUTH_REGISTER_IP_MAX=5`

新增依赖：`argon2-cffi`。

### 后端测试（`backend/tests/auth/`，按顺序先写 RED）

1. `test_passwords.py`：策略边界（9、10、128、129 字符；缺字母；缺数字）、Argon2id 前缀、rehash。
2. `test_auth_api.py`：
   - 注册 201 并自动登录，Cookie 属性正确；
   - 重复邮箱 409，大小写变体同样 409；
   - 登录 200 / 401 / 403；
   - 登出后旧 Cookie 返回 401；
   - 过期和空闲超时会话失效；
   - 令牌在库中只存哈希。
3. `test_csrf_cors.py`：缺少或不匹配的 CSRF 头返回 403 `csrf_failed`；非法 Origin 被拒；配置 `*` 时启动报错。
4. `test_rate_limit.py`：第 6 次登录返回 429 并带 Retry-After；IP 维度阈值；注册阈值；时钟推进后恢复。
5. `test_account_api.py`：修改资料；改密后所有会话失效；当前密码错误返回 400。
6. `test_admin_users_api.py`：
   - member 和 viewer 访问返回 403；
   - 分页与过滤；
   - 禁用后目标会话立即 401；
   - 最后管理员保护（含并发场景）返回 409；
   - 禁用自己返回 400；
   - 存在其他管理员时允许自降级。
7. `test_resource_isolation.py`：
   - 用户 B 访问 A 的文件、解析、分块、embedding 资源返回 404；
   - viewer 执行写操作返回 403；
   - 匿名访问返回 401。
8. `test_search_isolation.py`：
   - B 无数据而 A 有数据时，B 搜索返回 404；
   - 计数和召回都只包含本人数据；
   - 相同 query 和 session_id 下 L1/L2 不跨用户命中；
   - 交错请求的指纹互不覆盖。
9. `test_cli.py`：create-admin、promote-existing、claim 的 dry-run/confirm/幂等，以及默认用户不可登录。
10. 迁移测试：在空库和含历史数据的库上执行 upgrade、downgrade、upgrade。

### 前端测试（Vitest）

- `client.spec`：CSRF 头附带与重试；401 回调；`ApiError` 字段解析。
- `guards.spec`：safeRedirect 拒绝 `https://x`、`//x`、`/\x`、`\\x`；匿名访问重定向；guestOnly 跳转；admin 页面不发请求。
- `user.store.spec`：epoch 递增并丢弃迟到响应；logout 调用服务端接口；跨标签页登出。
- `chat.store.spec`：A/B 账号历史隔离且 A 可恢复；旧键 `knowra:chat` 不被导入。
- 各视图 spec：
  - Login：防重复提交、保留邮箱、错误提示 role=alert；
  - Register：本地校验未通过时不发请求；
  - Account：改密成功后重新登录；
  - AdminUsers：确认流程；last_admin 时回滚该行；
  - viewer 账号的写操作按钮处于禁用状态。

### 验证命令

- `uv run ruff check . && uv run ruff format --check . && uv run pytest`
- `uv run alembic upgrade head`
- `npm run lint && npm run test && npm run build`
- 本地浏览器验证：320px 宽度、同一浏览器切换账号、跨标签页登出。

### 回滚

- 部署前先备份数据库。
- 回滚到旧版本代码会恢复默认用户旁路，因此回滚期间必须关闭外部访问。
