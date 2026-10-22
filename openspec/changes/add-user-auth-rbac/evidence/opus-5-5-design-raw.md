# knowra 用户体系设计方案（认证 + RBAC + 资料隔离）

> 本文只是设计，所有内容都基于只读调研。我没有修改任何文件，没有写生产代码，也没有运行测试、迁移或构建。

建议的 OpenSpec 变更名：**`add-user-auth-rbac`**

---

## 0. 结论速览

| 主题 | 决定 |
|---|---|
| 身份凭据 | 邮箱 + 密码。密码使用 **argon2id** 哈希，存放在独立的 `user_password_credentials` 表。这样遵循已归档决策“认证字段不放进 users 表” |
| 会话 | 数据库保存 opaque token 的 SHA-256 哈希，浏览器保存 **HttpOnly Cookie** `knowra_session`。Cookie 设置为 `Path=/api`、`SameSite=Lax`，`Secure` 由配置决定。会话同时有绝对过期和空闲过期，可以撤销 |
| CSRF | 使用 `SameSite=Lax`，并在所有不安全方法上做 **Origin / Sec-Fetch-Site 校验**。CORS 不允许 `*`，且只放行明确列出的请求头 |
| 角色 | 本轮只做 **`admin` / `member`** 两个系统角色，并通过权限常量做映射。**`viewer` 暂不做**，理由见 D6 |
| 资料隔离 | 每个用户只能访问自己的资料。admin 只管理账号，**也不能读取其他用户的资料** |
| 旧数据 | 继续归属 `DEFAULT_USER_ID`，原数据不搬迁。默认用户迁移后没有密码，不能登录。运维人员运行 `bootstrap-admin`，把默认用户认领为第一个管理员 |
| 最严重的现有漏洞 | `SearchService._vector_search` 和 `_count_total_embeddings` **会检索所有用户的数据**。搜索响应 L1、查询重写 L1/L2 缓存和知识库指纹也没有按用户隔离。必须在本轮修复 |
| 前端 | 新增 `/login`、`/register`、`/settings/account`、`/admin/users`，加入全局路由守卫，统一处理 401。对话 localStorage 改为**按用户分别存储** |

---

## 1. 现状调研结论

### 1.1 固定默认用户的使用位置

- `backend/app/services/users.py`：`get_current_user(session)` 固定按 `DEFAULT_USER_ID` 查询；用户不可用时抛出 `CurrentUserUnavailableError`，路由返回 503。
- 调用位置：
  - `api/routes/uploads.py`
  - `document_parsing.py`、`document_chunking.py`、`document_embedding.py`
  - `pipeline_verification.py`、`users.py`
  - 后三个路由文件各自复制了一份 `require_current_user`。
- 各服务的归属传递是正确的：
  - 上传、解析、分块、embedding 和后台 dispatcher 都通过 `owner_user_id` 传递归属。
  - 存储 key 也带有 `owner_user_id`，例如 `uploads/{owner}/...`、`parsed/{owner}/...`、`chunks/{owner}/...`。
  - 按 ID 读取资源的接口基本都带有 `owner_user_id == current_user.id` 过滤。
- 迁移 `20260523_0001` 写入了默认用户 `00000000-...-0001`。
- 测试中大量使用 `seed_current_user(session)`，并断言 503。

### 1.2 必须修复的隔离风险

| # | 位置 | 问题 |
|---|---|---|
| R1 | `services/search.py::_vector_search` | 只过滤 `UploadedFile.deleted_at`，**没有按 owner 过滤**，会召回其他用户的分块 |
| R2 | `services/search.py::_count_total_embeddings` | 统计全表。`total_searched` 和 404 判断都会受到其他用户数据影响 |
| R3 | `services/search.py` 的 L1 响应缓存 | key 是客户端提供的 `session_id`，或由 history 派生的摘要。两个用户使用相同的 `session_id` 或 history 时，会**互相命中缓存** |
| R4 | `cache_manager.py` 的 L2（`l2:{normalized}`）和 `query_rewriter.py` 的 L1、去重 | L2 天然跨会话共享。在途去重 key 是 `{session_id}:{hash}`，同样可以被伪造 |
| R5 | `kb_fingerprint.compute_fingerprint` 和 `routes/search.py::update_fingerprint` | 指纹按全库计算，并写入**进程级共享实例**。多用户并发时，后写入的值会覆盖前一个，导致缓存被反复淘汰，状态也会互相干扰 |
| R6 | `front/src/stores/chat.ts` 中的 `localStorage["knowra:chat"]` | 对话历史包括回答和来源，但没有按用户隔离。同一浏览器换人登录后，**可以看到上一个人的记录** |
| R7 | `main.py` 的 CORS 配置 | `allow_credentials=True`，同时 `allow_methods/headers=["*"]`，而且没有禁止把 origin 配成 `*` |
| R8 | `api/documentParsing.ts`、`documentChunking.ts`、`embedding.ts`、`search.ts` | 直接调用 `fetch`，绕开了 `client.ts`，后续统一的 401 处理无法覆盖 |

---

## 2. 范围

### 2.1 本轮必须交付

1. 邮箱注册、登录、退出、记住我，会话可以过期和撤销。
2. 查看当前用户资料，修改显示名，修改密码。修改密码后撤销其他设备的会话，并轮换当前会话。
3. 系统角色 `admin` / `member`，管理员可以：
   - 查看用户列表，并按关键字、角色、状态筛选
   - 调整用户角色
   - 禁用或启用用户
   - 系统保证至少保留一名可登录的启用管理员
4. 通过 CLI 初始化管理员、认领旧数据、创建用户、重置密码和清理会话。
5. 所有资料接口、检索、对话、缓存和验证接口由**服务端强制按用户隔离**，修复 R1–R8。
6. 前端新增登录、注册、账户设置和用户管理四个页面，加入路由守卫、全局 401 处理、侧栏用户菜单和按用户隔离的对话存储，并适配移动端。
7. 新增配置项，加入启动期配置校验，同步更新 README 和 AGENTS 文档。

### 2.2 本轮不做

| 能力 | 原因 |
|---|---|
| 邮箱验证、找回密码 | 需要邮件服务。本轮通过 CLI `reset-password` 兜底 |
| OAuth / SSO / 2FA | 独立身份提供方需要单独设计。凭据表已独立，后续可以扩展 |
| 团队、工作区、共享知识库，以及 `viewer`、`editor` 等资源级角色 | 当前没有共享资源模型，见 D6 |
| 管理员查看、转移其他用户资料 | 涉及隐私边界，需要单独的审批和审计设计 |
| 用户软删除、注销账户 | 禁用已经能满足需求。资源转移和清理策略留到以后 |
| 头像上传和 `avatar_url` 编辑 | 字段保留为只读，避免引入 URL 和 XSS 风险 |
| 邮箱修改 | 需要验证流程 |
| 服务端保存对话历史 | 对话仍保存在浏览器 localStorage，本轮只按用户隔离 |
| IP 级限流、注册防刷验证码 | 本轮只做账号级锁定，见风险 K2 |
| 持久化审计表 | 本轮只记录结构化日志 |

### 2.3 后续扩展方向

- `workspaces` / `workspace_members(role: owner|editor|viewer)`
- 资源增加 `workspace_id`
- 邀请注册
- 管理员强制下线
- 会话列表和“退出其他设备”
- 邮件找回密码
- 持久化审计日志
- IP 限流
- 服务端保存对话

---

## 3. 关键决策

**D1：凭据放在独立表。** 新增 `user_password_credentials`，`users` 表只增加账号属性 `role` 和 `last_login_at`。这遵循已归档设计 `2026-05-23-add-basic-user-foundation/design.md` Decision 1 的约定，也方便以后接入 OAuth 身份表。

**D2：使用数据库 opaque session，而不是 JWT。** 需要立即撤销的场景包括退出、禁用和修改密码。opaque session 通过一次主键或唯一索引查询即可校验。不采用 JWT 的原因是撤销需要额外黑名单，而且角色变更不能实时生效。

**D3：Cookie 属性。**
- `HttpOnly`
- `SameSite=Lax`，默认值
- `Path={API_PREFIX}`，即 `/api`
- 不设置 `Domain`
- `Secure` 由 `AUTH_COOKIE_SECURE` 控制，生产环境强制为 `true`
- 记住我时设置 `Max-Age`，否则作为浏览器会话 Cookie

**D4：CSRF 采用 SameSite 加 Origin 校验。** 不采用双提交 token。前后端同源部署，或通过 Vite proxy 访问时，Origin 校验已经足够，而且不需要前端保存 token。

**D5：密码算法使用 argon2id。**
- 依赖：`argon2-cffi`
- 参数：`m=19456 KiB, t=2, p=1`，符合 OWASP 最低推荐
- 登录成功后，如果 `check_needs_rehash` 返回需要重新哈希，就自动升级哈希
- **实施前置检查**：先确认 `uv add argon2-cffi` 能在 Python 3.14 上安装 wheel。
- 如果无法安装，**唯一预先批准的替代方案**是标准库 `hashlib.scrypt`，参数为 `n=2**15, r=8, p=1`，格式为 PHC 风格字符串。需要在 OpenSpec 中记录这次替换。

**D6：角色只做 admin 和 member。** 当前每个用户只拥有自己的资料，系统里没有共享资源。

- `viewer` 只有在“能看到别人共享给我的资料”时才有意义。在当前模型中，它只会变成“不能往自己的空库上传资料”的账号，没有实际用途。
- 为了给以后加入 viewer 留出空间，权限检查一律依赖权限常量，不直接判断角色名：
  - `knowledge:read`
  - `knowledge:write`
  - `users:manage`
- 当前映射：
  - `member` = read + write
  - `admin` = member 的权限 + manage
- 以后增加 viewer 时，只需要修改映射，并通过一次迁移放宽 CHECK 约束。

**D7：admin 不能越权读取资料。** 所有资料查询继续使用 `owner_user_id == current_user.id`，admin 没有例外分支。这样不会因为管理员身份产生旁路。

**D8：通过 CLI 认领旧数据。** 不移动数据，不改写 `owner_user_id`，也不改变存储路径。默认用户在被认领前没有凭据，因此无法登录。

**D9：缓存按“用户 + 该用户的知识库指纹”划分作用域。**
- 指纹不再写入共享实例。
- 指纹直接拼进缓存 key 的作用域前缀。
- 作用域构造统一放在 `SearchService` 内，并且 owner 是**必填参数**。没有用户就无法调用检索。

**D10：错误响应格式。** 新增的认证和授权错误使用统一格式：

```json
{"detail": "...", "code": "...", "field": null}
```

- `detail` 仍然是字符串，现有前端的 `detail` 解析逻辑保持兼容。
- 其他已有接口的错误不在本轮统一改造。

**D11：未认证时返回 401，不再返回 503。** 现有 spec 中“当前用户不可用返回 503”的场景要通过 MODIFIED 改为 401。

**D12：注册后自动登录。** `AUTH_REGISTRATION_ENABLED` 默认是 `true`。关闭后注册接口返回 403，用户只能由 CLI 创建。

---

## 4. 数据模型与迁移

### 4.1 表结构

**`users`**：只修改，不重建。

| 字段 | 变更 |
|---|---|
| `role` | 新增：`VARCHAR(16) NOT NULL DEFAULT 'member'`，加上 `CHECK ck_users_role IN ('admin','member')` |
| `last_login_at` | 新增：`TIMESTAMPTZ NULL` |
| `status` | 新增 `CHECK ck_users_status IN ('active','disabled')` |
| `email` | 保留 `uq_users_email`。**应用层只写规范化后的邮箱** |
| 索引 | 新增 `ix_users_role_status (role, status)` |

**`user_password_credentials`**：新增。

| 字段 | 类型 |
|---|---|
| `user_id` | UUID，主键，同时是外键 `users.id ON DELETE CASCADE` |
| `password_hash` | VARCHAR(255) NOT NULL |
| `password_changed_at` | TIMESTAMPTZ NOT NULL |
| `failed_login_count` | INT NOT NULL DEFAULT 0 |
| `last_failed_login_at` | TIMESTAMPTZ NULL |
| `locked_until` | TIMESTAMPTZ NULL |
| `created_at`、`updated_at` | TIMESTAMPTZ NOT NULL |

**`auth_sessions`**：新增。

| 字段 | 类型和说明 |
|---|---|
| `id` | UUID，主键。日志里使用这个字段，不记录 token |
| `user_id` | UUID，外键 `users.id ON DELETE CASCADE`，建立索引 |
| `token_hash` | CHAR(64)，唯一。值为 `sha256(token)` 的十六进制字符串；**原始 token 绝不入库** |
| `remember_me` | BOOL NOT NULL |
| `created_at`、`last_seen_at` | TIMESTAMPTZ NOT NULL |
| `expires_at` | TIMESTAMPTZ NOT NULL，绝对过期时间，建立索引 |
| `revoked_at` | TIMESTAMPTZ NULL |
| `revoke_reason` | VARCHAR(32) NULL，可选值：`logout`、`password_changed`、`user_disabled`、`password_reset`、`superseded` |
| `user_agent` | VARCHAR(255) NULL，截断保存 |
| `ip_address` | VARCHAR(64) NULL |

**“可登录的启用管理员”的定义：**

```
role='admin' AND status='active' AND deleted_at IS NULL AND 存在凭据记录
```

末位管理员保护和 `bootstrap-admin` 判断都使用这一个定义。

### 4.2 Alembic 迁移 `20260820_0001_add_user_auth_and_roles.py`

`down_revision` 为 `20260812_0002`。

**`upgrade` 按以下顺序执行：**

1. 给 `users` 增加 `role`，`server_default='member'`。
2. 给 `users` 增加 `last_login_at`。
3. 执行 `UPDATE users SET status='disabled' WHERE status NOT IN ('active','disabled')`。这是保守处理；现有数据实际上只有 `active`。
4. 加上 `ck_users_status` 和 `ck_users_role`。
5. 规范化邮箱：
   - **先检查** `lower(trim(email))` 是否有重复。
   - 有重复时，抛出包含冲突数量的明确错误，并中止迁移。
   - 没有重复时，执行 `UPDATE users SET email=lower(trim(email)) WHERE email IS NOT NULL`。
6. 创建 `user_password_credentials`、`auth_sessions` 和对应索引。
7. **不修改默认用户**：角色保持 `member`，也不给它创建凭据。

**`downgrade`：**
- 删除两张新表、新约束、新索引和新列。
- 这会丢失凭据和会话；用户行与资源归属不受影响。

**SQLModel 模型需要同步声明约束。** 测试使用 SQLite 的 `create_all`。

**实现注意事项：** SQLite 读回的 `DateTime(timezone=True)` 是 naive datetime。所有过期判断都要经过 `ensure_utc(dt)`，把 naive 值视为 UTC，否则 Python 中会出现 aware 和 naive 比较的异常。

### 4.3 旧数据上线步骤

运维流程写入 README：

1. 备份 PostgreSQL 和 `storage/`。
2. 执行 `uv run alembic upgrade head`。此时所有资料接口都返回 401，系统处于锁定状态，旧数据不会暴露。
3. 执行 `uv run python -m app.cli.users bootstrap-admin --email you@example.com --display-name 你的名字`。
   - 命令通过 getpass 交互输入两次密码，或使用 `--password-stdin`。
   - 默认用户存在、未软删除且**没有凭据**时，命令把它**认领**为管理员：写入规范化邮箱、显示名、`role=admin` 和凭据。原有上传和文档继续归属这个账号。
   - 加上 `--no-claim-legacy` 时，命令创建一个新的管理员，旧数据暂不认领。以后可以通过 `create-user --claim-legacy` 认领给其他人。
   - 如果已经存在可登录的启用管理员，命令拒绝执行，退出码为 2。之后只能通过界面提升管理员。
4. 启动应用并登录。前端检测到当前用户 ID 等于旧默认用户 ID 时，把旧 `knowra:chat` 迁移到新 key。

**回滚：**
- 先回滚代码，再执行 `alembic downgrade -1`。
- 旧版代码仍会解析 `DEFAULT_USER_ID`。该用户行仍然存在；如果已被认领，只是邮箱和显示名发生变化，不影响旧代码。
- 新注册用户的数据会保留，外键仍有效，但在旧版本中无法访问。

---

## 5. 认证与会话

### 5.1 规范化与密码策略

服务端规则是唯一标准。前端只镜像其中一部分规则，用于即时提示。

- **邮箱：**
  - 先去掉首尾空白，再做 NFKC 规范化，然后转成小写，使用 `.lower()`。
  - 长度不超过 254；本地部分长度 1–64。
  - 必须匹配 `^[^@\s]+@[^@\s]+\.[^@\s]+$`。
  - 不满足时返回 422，`code=invalid_email`，`field=email`。
- **显示名：**
  - 去掉首尾空白后长度 1–100。
  - 不能包含控制字符。
  - 不满足时返回 422，`code=invalid_display_name`。
- **密码：**
  - 先做 NFKC 规范化。
  - 长度 10–128 个字符。
  - 至少包含 5 个不同字符。
  - 不能在本地常见密码表中，大小写不敏感。词表文件为 `app/services/data/common_passwords.txt`，约 1,000 条。
  - 不能等于完整邮箱或邮箱本地部分，大小写不敏感。
  - 不满足时返回 422，`code=weak_password`，`field=password`，`detail` 说明具体是哪条规则没有通过。
  - 不设置大写、数字等字符组成要求，符合 NIST 800-63B。
- **新密码不能与旧密码相同：** 返回 422，`code=password_unchanged`。

### 5.2 会话生命周期

| 场景 | 行为 |
|---|---|
| 登录或注册成功 | 生成 `secrets.token_urlsafe(32)`，保存它的 SHA-256；设置 Cookie；写入 `users.last_login_at`；顺便删除该用户 7 天前已过期或已撤销的会话 |
| 每次请求校验 | 根据 Cookie 计算哈希，联表查询 `auth_sessions` 和 `users`。要求：`revoked_at IS NULL`，`now < expires_at`，`now < last_seen_at + idle_timeout`，`users.status='active'`，`users.deleted_at IS NULL` |
| 滑动续期 | 只有当 `now - last_seen_at > AUTH_SESSION_TOUCH_INTERVAL_SECONDS` 时才更新 `last_seen_at`，用节流避免每次请求都写数据库。**不会延长 `expires_at`** |
| 过期时间 | 普通会话 12 小时，Cookie 不设置 Max-Age；记住我会话 30 天，并设置 `Max-Age`。空闲过期默认 7 天 |
| 退出 | 撤销当前会话，原因是 `logout`，并清除 Cookie。没有会话时也返回 204，保证幂等 |
| 修改密码 | 撤销该用户的**全部**会话，原因是 `password_changed`；然后签发新会话并设置新 Cookie |
| 禁用用户 | 撤销该用户全部会话，原因是 `user_disabled`。由于每次请求都会读取 `status`，即使撤销失败，禁用也会立即生效 |
| 角色变更 | 不撤销会话。每次请求都从数据库读取角色，变更会立即生效 |
| 会话无效 | 返回 401，并通过 `Set-Cookie` 删除 Cookie |

### 5.3 登录防爆破

- **邮箱不存在：**
  - 使用启动时懒加载生成的 dummy hash 执行一次 `verify`，让响应时间接近邮箱存在的情况。
  - 返回 401 `invalid_credentials`。
  - 不记录这个邮箱。
- **密码错误：**
  - `failed_login_count += 1`。
  - 达到 `AUTH_LOGIN_MAX_FAILURES`（默认 5）时，设置 `locked_until = now + AUTH_LOGIN_LOCKOUT_MINUTES`（默认 15），并把计数清零。
- **账号处于锁定期：**
  - 返回 429 `too_many_attempts`，同时带 `Retry-After` 秒数。
  - 锁定期内不校验密码。
- **登录成功：** 计数清零，`locked_until` 设为 NULL。
- **账号已禁用且密码正确：** 返回 403 `account_disabled`。只有密码正确时才透露“已禁用”。
- **修改密码时当前密码错误：** 返回 **400** `current_password_incorrect`，并计入失败次数。这里**不能返回 401**，否则前端会误判为会话失效并退出登录。

### 5.4 CSRF 与 CORS

新增纯 ASGI 中间件 `OriginCheckMiddleware`：

- 放在 CORS 中间件之内，`RequestLoggingMiddleware` 之外。
- 只检查 `{api_prefix}/*` 下的 `POST/PUT/PATCH/DELETE` 请求：
  - 有 `Origin` 请求头时，它必须在 `settings.cors_origins` 中，否则返回 403 `csrf_origin_rejected`。
  - 没有 `Origin`，但 `Sec-Fetch-Site == "cross-site"` 时，返回 403。
  - 两个请求头都没有时放行。这类请求来自非浏览器客户端，不存在 CSRF 风险。
- `BACKEND_CORS_ORIGINS` 同时作为可信来源白名单。生产环境必须配置为前端的公网 origin，未配置时直接拒绝请求。
- 通过 Vite proxy 访问时，Origin 是 `http://localhost:5173`；`changeOrigin` 只改 Host，所以这个 origin 仍会被白名单接受。

CORS 修改：
- `allow_methods=["GET","POST","PATCH","DELETE","OPTIONS"]`
- `allow_headers=["Accept","Content-Type","X-Trace-ID"]`

`Settings` 校验器：
- `cors_origins` 中包含 `*` 时，启动报错。
- `app_env ∈ {production, prod, staging}` 且 `auth_cookie_secure=false` 时，启动报错。
- `auth_cookie_samesite="none"` 但 `secure=false` 时，启动报错。

---

## 6. 角色与权限

`app/core/permissions.py` 定义：

- `Role`：`admin`、`member`
- `Permission`：`KNOWLEDGE_READ`、`KNOWLEDGE_WRITE`、`USERS_MANAGE`
- `ROLE_PERMISSIONS`：两个角色到权限集合的映射

`app/api/deps.py` 提供：

- `get_auth_context`：返回 `AuthContext(user, auth_session)`
- `CurrentUserDep`
- `require_permission(perm)`：返回可在路由上使用的依赖

| 接口 | 权限 |
|---|---|
| `GET /health`、`GET /auth/options`、`POST /auth/register`、`POST /auth/login`、`POST /auth/logout` | 公开 |
| `GET/PATCH /users/me`、`POST /users/me/password` | 已登录 |
| 所有 GET 资料接口、`POST /search`、流水线验证接口 | `knowledge:read` 加 owner 过滤 |
| `POST /uploads`、`/uploads/{id}/parse`、`/rechunk`、重新 embedding | `knowledge:write` 加 owner 过滤 |
| `/admin/*` | `users:manage`；不满足时返回 403 `forbidden` |

**管理员规则：**

- **目标用户不存在或已软删除：** 返回 404 `user_not_found`。
- **管理员修改自己的 `status`：** 返回 409 `cannot_modify_self_status`。
- **末位管理员保护：** 如果变更后可登录的启用管理员数量会变成 0，返回 409 `last_admin`。适用场景包括降级、禁用，以及自己降级自己。
- **并发控制：**
  - 在同一个事务中，用 `SELECT ... FOR UPDATE` 锁住全部启用管理员行，再计数。
  - PostgreSQL 会生效，SQLite 测试会忽略这个锁。
  - 测试只覆盖串行语义；并发场景在 design 中作为 PostgreSQL 手工验证项。
- **禁用用户：** 在同一事务中撤销该用户的全部会话。
- **至少修改一个字段：** 请求中 `role` 和 `status` 至少有一个，否则返回 422 `empty_update`。

---

## 7. 资料隔离与旁路封堵

| 位置 | 修改 |
|---|---|
| 5 个资料路由文件 | 删除各自的 `require_current_user` 和 `get_current_user(session)`，改为 `CurrentUserDep` 或 `require_permission(...)`。保留原有 owner 过滤；跨用户访问统一返回 **404**，不返回 403，以免泄露资源是否存在 |
| `services/users.py` | 删除 `DEFAULT_USER_ID` 的解析逻辑。常量改名为 `LEGACY_DEFAULT_USER_ID`，只给 CLI 和测试使用。`CurrentUserUnavailableError` 删除 |
| `SearchService.search` | 新增**必填**关键字参数 `owner_user_id: UUID` 和 `kb_fingerprint: str` |
| `_vector_search` | 增加 `DocumentEmbedding.owner_user_id == owner`、`ParsedDocument.owner_user_id == owner`、`UploadedFile.owner_user_id == owner`，三层过滤都保留 |
| `_count_total_embeddings` | 只统计当前用户的数据，并联表排除已软删除的上传。`total_searched` 和 404 都按用户语义计算 |
| 缓存作用域 | `scope = f"u:{owner}:{fp}"`。`_resolve_session_id` 返回 `f"{scope}:{sid}"`；无论 sid 是客户端显式传入，还是由 history 派生，都带上作用域。如果既没有 sid 也没有 history，就不使用缓存，保持现有行为 |
| `QueryRewriter.rewrite` | 新增 `cache_namespace: str \| None`，`SearchService` 传入 `scope`。**为 None 时完全跳过 L2 查询和写入。** L1、在途去重和不满意检测都使用已经带作用域的 session id |
| `CacheManager.lookup_l2/store_l2` | 新增 `namespace` 参数，key 改为 `l2:{namespace}:{normalized}` |
| `compute_fingerprint(session, *, owner_user_id)` | owner 是必填参数，按用户统计 embedding 数和成功任务的最近更新时间 |
| `routes/search.py` | **不再调用** `update_fingerprint`。共享实例的指纹保持 None，`_fingerprint_matches` 会跳过校验；路由把按用户计算的指纹传给 `SearchService` |
| `routes/uploads.py` | `invalidate_all_search_caches(session_id=f"u:{user.id}:")` 只清理当前用户的 L1。利用现有的前缀失效逻辑，需要确认它能按 `u:{id}:` 前缀匹配；其他用户的缓存不受影响 |
| `pipeline_verification._load_document_chain` | 读取 `UploadedFile` 时也加上 owner 条件，作为额外防线 |
| 后台任务 | 继续沿用 `job.owner_user_id`，不依赖请求中的用户，不需要修改 |
| 路由清单测试 | 遍历 `app.routes`。除公开白名单外，所有 `/api` 路由在没有 Cookie 时都必须返回 401。以后新增接口如果忘了加鉴权，这个测试会失败 |

---

## 8. API 契约

### 8.1 接口

| 方法和路径 | 请求 | 成功响应 | 主要错误 |
|---|---|---|---|
| `GET /api/auth/options` | — | 200 `{"registration_enabled":true,"password_min_length":10}` | — |
| `POST /api/auth/register` | `{email, password, display_name}` | 201 `{"user": MeRead}` 和 Set-Cookie | 403 `registration_closed`，409 `email_taken`，422 `invalid_email` / `weak_password` / `invalid_display_name` |
| `POST /api/auth/login` | `{email, password, remember_me=false}` | 200 `{"user": MeRead}` 和 Set-Cookie | 401 `invalid_credentials`，403 `account_disabled`，429 `too_many_attempts` |
| `POST /api/auth/logout` | — | 204，并清除 Cookie | — |
| `GET /api/users/me` | — | 200 `MeRead` | 401 `auth_required` / `session_invalid` / `account_disabled` |
| `PATCH /api/users/me` | `{display_name}` | 200 `MeRead` | 422 `invalid_display_name` |
| `POST /api/users/me/password` | `{current_password, new_password}` | 204 和新的 Set-Cookie | 400 `current_password_incorrect`，422 `weak_password` / `password_unchanged`，429 |
| `GET /api/admin/users?q=&role=&status=&offset=0&limit=20` | `limit` 范围 1–100 | 200 `{"items":[AdminUserRead],"total","offset","limit"}` | 401，403 `forbidden` |
| `PATCH /api/admin/users/{id}` | `{role?, status?}` | 200 `AdminUserRead` | 404 `user_not_found`，409 `last_admin` / `cannot_modify_self_status`，422 `empty_update` |

**响应字段：**

- `MeRead`：保留现有 `UserRead` 的全部字段以保持兼容，`deleted_at` 始终为 null；另外增加 `role` 和 `last_login_at`。
- `AdminUserRead`：

```
id, email, display_name, role, status, can_login(bool), is_self(bool), created_at, last_login_at
```

**示例：**

```json
// 401
{"detail": "登录已失效：会话已过期或已被撤销，请重新登录。", "code": "session_invalid", "field": null}
// 409
{"detail": "无法完成操作：系统必须至少保留一名启用状态的管理员。请先提升其他用户为管理员。", "code": "last_admin", "field": null}
```

**错误格式：**

- `app/core/errors.py` 定义 `AppError(status_code, code, detail, field=None, headers=None)`，并在 `create_app` 中注册异常处理器。
- `detail` 使用中文，内容要说明“发生了什么场景、根本原因、用户应该怎么做”。
- Pydantic 生成的 422 仍保持 FastAPI 默认格式，即 `detail` 为列表。前端取第一条 `msg`。

**跨端兼容说明：**

- `SearchRequest` 和 `SearchResponse` 的字段不变。
- `total_searched` 的语义改为“当前用户的向量数”。
- 原来的 503 “Current user is unavailable” 改为 401。

---

## 9. 前端设计

### 9.1 API 层

**`api/client.ts`：**

- 新增 `apiFetch(path, init & {skipAuthRedirect?})`：
  - 统一设置 `credentials: "include"`。
  - 自动加入 `X-Trace-ID`。
  - 收到 401 且不是 `skipAuthRedirect` 请求时，调用 `setUnauthorizedHandler(fn)` 注册的处理函数。
- 新增 `ApiError extends Error {status, code, detail, field}`：
  - 能解析字符串形式的 `detail`。
  - `detail` 是 422 列表时，取第一条 `msg`。
  - `message` 设为 `detail`，现有代码使用 `error.message` 不受影响。
- 新增 `apiPostJson` 和 `apiPatchJson`。
- `apiGet` 和 `apiPostForm` 改为基于 `apiFetch` 实现。

**需要改用 `apiFetch` 的模块：** `search.ts`、`documentParsing.ts`（同时删除重复的 `buildApiUrl`）、`documentChunking.ts`、`embedding.ts`。各模块保留现有错误类，以减少其他代码的改动。

**新增 API 文件：**

- `api/auth.ts`：`getAuthOptions`、`login`、`register`、`logout`。其中 login 和 register 设置 `skipAuthRedirect`。
- `api/users.ts`：扩展 `User` 类型，增加 `role` 和 `last_login_at`；新增 `updateMyProfile`、`changeMyPassword`。
- `api/adminUsers.ts`：`listUsers`、`updateUser`。

**新增共享工具：**

- `shared/auth/errorMessages.ts`：把错误 code 映射成中文文案；没有映射时使用 `detail`。
- `shared/auth/passwordPolicy.ts`：前端镜像规则，包括长度、不同字符数和不能等于邮箱。
- `shared/auth/redirect.ts`：`sanitizeRedirect()`。只接受以 `/` 开头、不以 `//` 或 `/\` 开头、且不是 `/login` 或 `/register` 的路径；其他情况返回 `/`。

### 9.2 状态管理

**`stores/user.ts`：** 保留 `useUserStore` 这个名字，降低组件和测试的改动量。

- 状态：

```
currentUser, status: "unknown"|"loading"|"authenticated"|"anonymous", userError
```

- `isAdmin` getter
- actions：
  - `ensureLoaded()`：只请求一次 `/users/me`。返回 401 时把状态设为 `anonymous`，不当作错误。
  - `login`、`register`、`logout`、`updateProfile`、`changePassword`
  - `handleSessionExpired()`：会话失效时调用
- 认证成功后调用 `chatStore.hydrateForUser(user.id)`。
- 退出或会话失效时调用 `chatStore.reset()`。

**`stores/chat.ts`：**

- 初始状态改为空，不再在 store 创建时读取 localStorage。
- storage key 改为 `knowra:chat:v2:{userId}`。
- `hydrateForUser(id)`：
  - 当 `id === LEGACY_DEFAULT_USER_ID` 且新 key 不存在时，把旧 `knowra:chat` 迁移到新 key，然后删除旧 key。
  - 其他用户**不读取**旧 key。
- `reset()`：清空内存中的对话状态。
- 退出后，还在进行中的请求返回时，会找不到对应会话；`updateBubble` 已经会记录告警并跳过，不需要额外处理。

### 9.3 路由和全局 401

| 路由 | 组件 | meta |
|---|---|---|
| `/login` | `views/auth/LoginView.vue` | `guestOnly` |
| `/register` | `views/auth/RegisterView.vue` | `guestOnly` |
| `/` | `ChatLayout` | `requiresAuth` |
| `/verify` | `VerificationView` | `requiresAuth` |
| `/settings/account` | `views/AccountView.vue` | `requiresAuth` |
| `/admin/users` | `views/admin/AdminUsersView.vue` | `requiresAuth`、`requiresAdmin` |

`/home` 和 `/chat` 仍重定向到 `/`。

**`beforeEach` 守卫：**

1. 先 `await userStore.ensureLoaded()`。
2. 访问需要登录的页面但当前是匿名状态时，跳到 `/login?redirect=<fullPath>`。
3. 已登录用户访问 `guestOnly` 页面时，跳到 `/`。
4. 非管理员访问 `requiresAdmin` 页面时，跳到 `/`，同时设置一次性提示“需要管理员权限”。

**`main.ts`：**

- 在 `app.use(router)` 之后注册 unauthorized handler：
  - 使用一个标志位避免并发 401 重复处理。
  - 调用 `handleSessionExpired()`。
  - 执行 `router.replace({name:"login", query:{redirect, reason: code==="account_disabled" ? "disabled" : "expired"}})`。

### 9.4 界面设计

所有页面只使用语义令牌：`paper`、`surface`、`ink`、`line`、`brand`，以及 `--radius-*` 和 `--shadow-*`。不使用外部字体。

**`components/auth/AuthShell.vue`：**
- 全屏 `bg-paper` 页面，内容居中。
- 顶部复用“知”字徽标、`font-display` 的“知寻”和 `KNOWRA` 字标，副标题为“把你的资料变成可追溯的知识库”。
- 卡片宽度 `max-w-sm`。
- 在 `sm:` 及以上尺寸显示 `bg-surface border-line shadow-card rounded-[var(--radius-card)]`。
- 小于 `sm` 时去掉边框，内容铺满宽度，左右留 `px-5`。

**`components/auth/PasswordField.vue`：**
- 有 label。
- 提供显示和隐藏密码按钮，按钮使用 `aria-pressed`。
- 支持 `autocomplete` 属性。
- 错误信息通过 `aria-describedby` 关联，ID 使用 `uniqueId()` 生成。

**LoginView：**
- 字段：邮箱（`autocomplete=email`，`inputmode=email`）、密码（`current-password`）、“保持登录 30 天”。
- 提交中禁用按钮，按钮文字为“登录中…”。
- 表单级错误使用 `role="alert"`。
- 根据 `reason` 显示提示：
  - `expired`：“登录已过期，请重新登录”
  - `disabled`：“账户已停用，请联系管理员”
  - `logged_out`：“已安全退出”
- 只有开放注册时才显示“注册”链接。

**RegisterView：**
- 字段：显示名、邮箱、密码（`new-password`）、确认密码。
- 实时显示密码规则清单，每项显示通过或未通过，并使用 `aria-live=polite` 播报。
- 返回 `email_taken` 时，在邮箱字段下显示错误，并给出“去登录”链接。
- 注册关闭时，页面只显示提示和返回登录的链接。

**所有表单输入：** 使用 `text-base` 字号，防止 iOS 自动放大；点击区域至少 44px。

**`components/layout/PageShell.vue`：**
- 账户设置和用户管理页使用这个页面壳。
- 顶栏 `h-13 border-b border-line bg-paper/90`，左侧是“← 返回对话”，中间是页面标题。
- 内容最大宽度 `max-w-3xl`。

**AccountView：**
- 使用两个 `PanelSection`：
  - “基本资料”：显示名可编辑；邮箱、角色徽章和注册时间只读。
  - “修改密码”：当前密码、新密码、确认密码。成功后提示“密码已更新，其他设备已退出”。

**AdminUsersView：**
- 顶部有搜索框和角色、状态筛选。
- 宽度 ≥768px 时显示表格，列为“用户 / 角色 / 状态 / 最近登录 / 操作”。
- 宽度 <768px 时改为卡片列表。
- 角色使用 `<select>` 修改。
- 禁用和启用通过已有 `ConfirmDialog` 确认，并设置 `danger`。
- 当前用户所在行标记“（你）”，状态按钮禁用。
- `can_login=false` 的用户显示“未激活（旧数据账户）”。
- `409 last_admin` 错误在该行内显示。
- 分页每页 20 条。
- 如果管理员把自己降级，系统刷新 `/users/me`，然后跳转到 `/`。

**SidebarUser：**
- 删除 `onMounted` 中加载用户的逻辑，因为守卫已经加载。
- 用户信息区域改为按钮，带 `aria-haspopup="menu"`，打开向上弹出的菜单。
- 菜单项：账户设置；用户管理（仅 admin 可见）；退出登录。
- 管理员显示“管理员”小徽章。
- 菜单行为：
  - Esc 关闭菜单并把焦点还给触发按钮。
  - 方向键在菜单项之间移动。
  - 点击外部时关闭。
- 在移动端，菜单位于抽屉内，交互方式相同。

**KnowledgeInfo：** 把 `<a href="/verify">` 改为 `RouterLink`，避免整页刷新。

---

## 10. 配置与运维

新增到 `Settings` 和 `.env.example`：

```
AUTH_REGISTRATION_ENABLED=true
AUTH_SESSION_COOKIE_NAME=knowra_session
AUTH_COOKIE_SECURE=false            # 生产环境必须为 true（启动校验）
AUTH_COOKIE_SAMESITE=lax            # lax|strict|none（none 需要 secure）
AUTH_SESSION_TTL_HOURS=12
AUTH_SESSION_REMEMBER_TTL_DAYS=30
AUTH_SESSION_IDLE_TIMEOUT_HOURS=168
AUTH_SESSION_TOUCH_INTERVAL_SECONDS=300
AUTH_LOGIN_MAX_FAILURES=5
AUTH_LOGIN_LOCKOUT_MINUTES=15
AUTH_ARGON2_MEMORY_KIB=19456
AUTH_ARGON2_TIME_COST=2
AUTH_ARGON2_PARALLELISM=1
```

测试 fixture 把 argon2 参数降到 `8 KiB / 1 / 1`，以提高测试速度。

**CLI：** `backend/app/cli/users.py`，使用 argparse，运行方式为 `uv run python -m app.cli.users <cmd>`。

| 命令 | 用途 |
|---|---|
| `bootstrap-admin` | 初始化第一个管理员，默认认领旧数据 |
| `create-user --role` | 创建用户，可加 `--claim-legacy` 认领旧数据 |
| `reset-password` | 重置密码，撤销全部会话，并解除锁定 |
| `purge-sessions --older-than-days 30` | 清理旧会话 |

CLI 约定：
- 密码不能通过命令行参数传入；只能用 getpass，或使用 `--password-stdin`。
- 退出码：0 成功，1 参数或校验错误，2 前置条件不满足。

**日志：** 遵循 `get_logger` 的写法，事件名固定，动态值放在关键字字段中，例如：

```
logger.info("用户登录成功", user_id=..., auth_session_id=..., remember_me=True)
logger.warning("用户登录失败", reason="wrong_password", user_id=...)
logger.info("管理员调整用户", actor_user_id=..., target_user_id=..., changed_fields=["role"])
```

日志中**禁止出现**：密码、原始 token、`token_hash`、Cookie 请求头、未知邮箱。

**生命周期和优雅停机：** 本变更不新增后台任务、线程、长连接或模型资源。会话校验和续期都在请求事务中同步完成，因此不适用额外的 graceful shutdown 设计。CLI 是短进程，每个命令使用一个 DB session，结束时用 `with` 关闭。

---

## 11. 文件改动清单

**后端新增：**

- 迁移：`alembic/versions/20260820_0001_add_user_auth_and_roles.py`
- 模型：`app/models/user_credential.py`、`app/models/auth_session.py`
- 核心模块：`app/core/errors.py`、`app/core/permissions.py`、`app/core/csrf.py`
- 依赖：`app/api/deps.py`
- 路由：`app/api/routes/auth.py`、`app/api/routes/admin_users.py`
- Schema：`app/schemas/auth.py`、`app/schemas/admin_user.py`
- 服务：`app/services/passwords.py`、`app/services/auth_sessions.py`、`app/services/auth.py`、`app/services/user_admin.py`
- 数据文件：`app/services/data/common_passwords.txt`
- CLI：`app/cli/__init__.py`、`app/cli/users.py`
- 测试辅助：`tests/auth_helpers.py`，提供 `make_user`、`login_as`、`override_current_user` 和快速哈希器

**后端修改：**

- `models/user.py`、`models/__init__.py`
- `schemas/user.py`
- `services/users.py`
- `api/router.py`
- `api/routes/users.py`、`uploads.py`、`document_parsing.py`、`document_chunking.py`、`document_embedding.py`、`pipeline_verification.py`、`search.py`
- `services/search.py`、`query_rewriter.py`、`cache_manager.py`、`kb_fingerprint.py`、`pipeline_verification.py`
- `core/config.py`
- `main.py`：注册异常处理器、`OriginCheckMiddleware`，收紧 CORS
- `pyproject.toml`：加入 `argon2-cffi`
- `.env.example`
- 现有测试：
  - 把 `seed_current_user` 和 503 断言改为认证 fixture 和 401 断言
  - 给 `search()` 和 `compute_fingerprint` 补必填参数
  - L2 测试改为传入 namespace

**前端新增：**

- API：`api/auth.ts`、`api/adminUsers.ts`
- 共享工具：`shared/auth/{errorMessages,passwordPolicy,redirect}.ts`
- 组件：`components/auth/{AuthShell,PasswordField}.vue`、`components/layout/PageShell.vue`
- 页面：`views/auth/{LoginView,RegisterView}.vue`、`views/AccountView.vue`、`views/admin/AdminUsersView.vue`
- 对应测试

**前端修改：**

- API：`api/client.ts`、`users.ts`、`search.ts`、`documentParsing.ts`、`documentChunking.ts`、`embedding.ts`
- Store：`stores/user.ts`、`chat.ts`
- `router/index.ts`、`main.ts`
- `components/sidebar/{SidebarUser,KnowledgeInfo}.vue`
- 测试：
  - `router/__tests__/index.spec.ts`：路由数量要更新
  - `stores/*.test.ts`
  - `sidebar.spec.ts`

**文档：**

- 根目录 `README.md`：首次启动需要执行 `bootstrap-admin`
- `backend/README.md`：认证配置、CLI、迁移和回滚
- `front/README.md`：登录流程、本地开发 Cookie 和代理说明
- `backend/AGENTS.md`：鉴权依赖约定和“禁止绕过 owner 过滤”
- `front/AGENTS.md`：禁止在 `src/api` 中直接调用 `fetch`；状态必须按用户隔离
- 根目录 `AGENTS.md` 的“后端职责”：补充认证和授权

**OpenSpec：**

- 新增 spec：`user-authentication`、`user-access-control`、`account-settings`
- MODIFIED：
  - `basic-user-foundation`：当前用户解析改为基于会话；删除“不提供注册 / 前端不提供认证入口”
  - `semantic-search`：检索范围改为当前用户
  - `query-rewriting-integration`：缓存按用户隔离
  - `file-upload-storage`、`document-parsing`、`document-chunking`、`document-embedding`、`pipeline-verification`：503 改为 401，并补充跨用户 404
  - `backend-module-logging`：删除 `default_user_id` 字段要求
  - `frontend-redesign`：localStorage 按用户隔离，侧栏增加用户菜单
- 开工前建议先归档已经全部勾选完成的 `polish-frontend-ui`，避免侧栏相关 spec 冲突。

---

## 12. TDD 分组

每组都按“红测试 → 评审确认 → 绿实现 → 重构”推进，并遵守 config.yaml 中的停顿要求。每个测试函数都要加中文注释。

| 组 | 内容 |
|---|---|
| **B0 测试基础设施** | `auth_helpers`、快速哈希器、已认证 TestClient fixture，不含业务逻辑 |
| **B1 迁移和模型** | 新列和 CHECK、两张新表、默认用户不变、邮箱规范化、规范化后重复时中止迁移、downgrade |
| **B2 密码和规范化** | 各条密码规则、NFKC、哈希往返、`needs_rehash`、dummy verify |
| **B3 会话服务** | 只保存哈希、绝对过期、空闲过期、撤销、轮换、续期节流、naive datetime |
| **B4 认证 API** | 注册、登录、退出、选项接口；Cookie 属性；锁定和 `Retry-After`；未知邮箱与密码错误的响应一致；注册关闭；禁用账号 |
| **B5 鉴权依赖** | 401 各个 code；路由清单测试；`require_permission` 返回 403 |
| **B6 CSRF / CORS / 配置校验** | Origin 白名单、`Sec-Fetch-Site`、`*` 和生产环境 Secure 的启动报错 |
| **B7 当前用户接口** | `PATCH /users/me`；修改密码会撤销其他会话、签发新 Cookie、错误当前密码返回 400 |
| **B8 管理员接口** | 403；筛选和分页；`last_admin`；不能修改自己的状态；禁用会撤销会话；`can_login` 和 `is_self` |
| **B9 隔离** | 每类资源的跨用户 404；检索只返回当前用户的数据；`total_searched` 和 404 按用户计算；各类缓存隔离 |
| **B10 CLI** | 认领旧数据、`--no-claim-legacy`、已有管理员时退出码 2、`create-user`、`reset-password`、`purge-sessions` |
| **B11 日志** | 抓取日志，断言其中没有密码、token 或 Cookie；遵守 logging style 测试 |
| **F1 client** | `credentials: include`、`ApiError` 解析、401 hook 和 `skipAuthRedirect`；约束测试：`src/api` 中除 `client.ts` 外不得出现 `fetch(` |
| **F2 API 模块** | auth、users、adminUsers 的路径和请求体 |
| **F3 user store** | 状态流转；登录和退出时联动 chat store；会话失效处理 |
| **F4 chat store** | 按用户分开存储 key；旧数据只迁移给旧默认用户；`reset` |
| **F5 路由守卫** | 四类重定向；`sanitizeRedirect` 的各种边界 |
| **F6 登录和注册页** | 校验、错误 code 映射、pending 状态、a11y 属性、注册关闭、`reason` 提示 |
| **F7 / F8 / F9** | AccountView、AdminUsersView、SidebarUser 菜单（包括键盘和 Esc 行为） |
| **V 验证** | 运行下面的门禁命令，再完成浏览器冒烟检查 |

**门禁命令：**

后端：

```
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head
```

前端：

```
npm run lint && npm run test && npm run build
```

**浏览器冒烟检查：**
- 需要分别检查桌面端和 375px 宽度。
- 流程：注册 → 上传 → 提问 → 退出 → 换另一个账号登录。
- 预期：看不到上一个账号的对话和资料，问答结果中也没有上一个账号的来源。

---

## 13. 验收矩阵

| ID | 前置条件和操作 | 期望结果 |
|---|---|---|
| A1 | 使用未注册邮箱 ` Foo@X.com ` 注册 | 201；保存的邮箱为 `foo@x.com`；`role=member`；返回 Set-Cookie，且包含 HttpOnly、SameSite=Lax、Path=/api |
| A2 | 用 `FOO@x.com` 再注册一次 | 409 `email_taken` |
| A3 | 使用 `password12` 这类常见弱密码注册 | 422 `weak_password`，`field=password` |
| A4 | 用错误密码登录，以及用不存在的邮箱登录 | 两者都返回 401 `invalid_credentials`，响应体相同 |
| A5 | 连续 5 次密码错误，然后输入正确密码 | 第 6 次请求返回 429，并带 `Retry-After` |
| A6 | 不带记住我登录，然后检查 Cookie | 没有 Max-Age；服务端 12 小时后返回 401 `session_invalid` |
| A7 | 退出后继续使用旧 Cookie | 返回 401；数据库中 `revoked_at` 不为空 |
| A8 | 设备 A 修改密码，设备 B 继续访问 | B 返回 401；A 拿到新 Cookie 后可以继续使用 |
| A9 | 修改密码时当前密码错误 | 400 `current_password_incorrect`，不是 401 |
| P1 | member 访问 `/api/admin/users` | 403 `forbidden` |
| P2 | 唯一管理员尝试把自己降级 | 409 `last_admin`，角色不变 |
| P3 | 管理员尝试禁用自己 | 409 `cannot_modify_self_status` |
| P4 | 管理员禁用用户 U | U 的下一次请求返回 401 `account_disabled`；U 再登录时返回 403 |
| P5 | 把 member 提升为 admin | 这个用户不需要重新登录，下一次请求就能访问 `/admin/*` |
| I1 | A 已上传资料，B 拿 A 的各类资源 ID 访问上传、解析文档、分段、分块、分块任务、embedding、验证和 rechunk 接口 | 全部返回 404，响应中不出现 A 的任何字段 |
| I2 | A 已有向量，B 没有向量，B 发起检索 | 404 “知识库中暂无…”；A 的分块不会出现在结果中 |
| I3 | A 和 B 都有向量，B 检索 A 资料中的原文 | 结果只包含 B 的 `parsed_document_id`；`total_searched` 等于 B 的向量数 |
| I4 | A 和 B 使用相同 `session_id`、相同 query 和相同 history | B 的响应不是缓存命中，`audit` 中的 `cache_hit=false`，内容来自 B 自己的库 |
| I5 | 启用查询重写，A 的 L2 中已有某个 query，B 用同一个 query 检索 | B 没有命中 L2，`cache_level` 不等于 `"L2"` |
| I6 | 遍历除公开白名单外的所有 `/api` 路由，并且不带 Cookie 请求 | 全部返回 401 |
| C1 | 请求头为 `Origin: https://evil.example` 的 POST `/api/auth/login` | 403 `csrf_origin_rejected` |
| C2 | 设置 `BACKEND_CORS_ORIGINS=*`，或在 `APP_ENV=production` 时设置 `AUTH_COOKIE_SECURE=false` | 启动时报错 |
| M1 | 已有旧数据，执行迁移后再执行 `bootstrap-admin` | 默认用户变为 admin；用新密码登录后能看到旧上传，并能检索旧资料 |
| M2 | 已有管理员时再次执行 `bootstrap-admin` | 退出码 2，数据库不变 |
| M3 | 规范化后存在重复邮箱时执行迁移 | 迁移中止，并给出明确错误 |
| F1 | 未登录访问 `/verify` | 跳到 `/login?redirect=/verify`，登录后回到 `/verify` |
| F2 | 使用 `?redirect=//evil.com` 登录 | 登录后跳到 `/` |
| F3 | 会话过期后发起任意 API 请求 | 自动跳到登录页，并提示“登录已过期” |
| F4 | 同一浏览器中 A 退出，B 登录 | B 的侧栏对话列表为空，不包含 A 的对话 |
| F5 | 375px 宽度访问登录、注册、账户设置和管理页 | 没有横向滚动；输入框字号 ≥16px；抽屉中的用户菜单可以操作 |
| L1 | 抓取完整认证流程的日志 | 日志中不出现明文密码、token 或 Cookie 值 |

---

## 14. 风险与已知限制

- **K1** 对话历史仍保存在本机，没有加密。其他用户无法在界面中看到，但可以通过 devtools 读取。后续通过服务端保存对话解决。
- **K2** 账号级锁定可以被他人恶意触发，使目标账号 15 分钟内无法登录。本轮接受这个取舍，后续加入 IP 限流。
- **K3** 注册返回 409 会暴露邮箱是否已注册。在没有邮件验证的情况下，本轮接受这个取舍。
- **K4** `SELECT FOR UPDATE` 的并发保护只能在 PostgreSQL 上手工验证。SQLite 测试只覆盖串行语义。
- **K5** 前端日志缓冲区（IndexedDB）不按用户隔离，可能包含查询文本。本轮先在 design 中记录，后续可在退出时清理。
- **K6** 如果 argon2-cffi 不能在 Python 3.14 上安装，按 D5 改用 scrypt，并在 OpenSpec 中记录。
