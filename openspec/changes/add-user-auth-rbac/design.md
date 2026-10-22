## Context

knowra 目前把所有请求解析为固定的 `DEFAULT_USER_ID`。`backend/app/services/users.py::get_current_user(session)` 被上传、解析、分块、向量化、流水线验证和 `/users/me` 路由直接调用，用户不可用时返回 503。各资源表已经带有 `owner_user_id`，按 ID 读取的接口也已按归属过滤，但存在以下旁路：

- `SearchService._vector_search` 与 `_count_total_embeddings` 检索全库，不按用户过滤。
- 搜索响应缓存、查询重写 L1/L2 缓存和在途去重以客户端 `session_id` 或 history 摘要为键，不同用户可以互相命中。
- `compute_fingerprint` 统计全库，并通过 `update_fingerprint` 写入进程级单例，多用户并发时互相覆盖。
- 前端对话历史固定存储在 `localStorage["knowra:chat"]`，换账号后仍可见。
- `search.ts`、`documentParsing.ts`、`documentChunking.ts`、`embedding.ts` 直接调用 `fetch`，无法统一处理 401。

设计来源：本设计由 `pi` 中的 `dtmaas/claude-opus-5-5` 产出两轮方案（原文见 `evidence/opus-5-5-design-raw.md` 与 `evidence/opus-5-5-synthesis-raw.md`），由实现模型收敛为下述唯一方案。采纳与偏离说明见文末“采纳说明”。

## Goals / Non-Goals

**Goals:**

- 邮箱密码注册（自动登录）、登录、退出、持久会话、会话撤销、资料修改与密码修改。
- 固定角色 `admin` / `member` / `viewer`，后端按权限常量强制授权；管理员可分页查看账号、调整角色、禁用与启用，系统始终保留至少一名有效管理员。
- 所有资料接口、检索、缓存与指纹按已认证用户隔离；管理员不因角色获得读取他人资料的能力。
- 前端提供登录、注册、账户、用户管理页面，路由守卫、统一 401 处理、按用户隔离的对话存储和只读用户的操作禁用说明。
- 通过 CLI 初始化管理员，并可显式认领旧默认用户的历史资料。

**Non-Goals:**

- 邮箱验证、邮件找回密码、OAuth/SSO/MFA、团队与共享知识库、服务端对话同步。
- 注册开关、IP 维度限流与验证码、会话列表与“退出其他设备”、空闲超时、记住我。
- 用户软删除/注销、邮箱修改、头像上传、持久化审计表、管理员用户列表的搜索与筛选。

## Decisions

### D1 凭据独立建表，`users` 只增加 `role`

新增 `user_credentials(user_id PK/FK users.id, password_hash, created_at, updated_at)`；`users` 增加 `role VARCHAR(16) NOT NULL DEFAULT 'member'` 与 `CHECK role IN ('admin','member','viewer')`。

理由：归档决策 `2026-05-23-add-basic-user-foundation` Decision 1 明确不把认证字段放进 `users`。没有凭据行的用户（例如迁移后的旧默认用户）天然无法登录。替代方案“`users.password_hash` 可空”少一张表，但与归档决策冲突，不采用。

### D2 数据库 opaque 会话 + HttpOnly Cookie

- 新增 `user_sessions(id UUID PK, user_id FK 索引, token_hash CHAR(64) 唯一, created_at, expires_at, revoked_at NULL)`。
- 令牌为 `secrets.token_urlsafe(32)`，库中只存 `sha256(token)` 十六进制；原始令牌只出现在 `Set-Cookie`。
- Cookie：`knowra_session`，`HttpOnly`、`SameSite=Lax`、`Path={API_PREFIX}`、`Max-Age=AUTH_SESSION_TTL_HOURS*3600`，`Secure` 由 `AUTH_COOKIE_SECURE` 控制。
- 有效条件：`revoked_at IS NULL`、`now < expires_at`、用户 `status='active'` 且 `deleted_at IS NULL`。每次请求都读取数据库中的最新用户和角色。
- 登录时若已携带旧会话 Cookie，先撤销旧会话再签发新会话。

理由：退出、禁用、改密都需要立即撤销；JWT 需要额外黑名单且角色变更不能实时生效。

### D3 CSRF：SameSite=Lax + Origin 校验

- `api_router` 级依赖 `verify_trusted_origin` 检查所有 `POST/PUT/PATCH/DELETE`：
  - 带 `Origin` 时必须属于 `BACKEND_CORS_ORIGINS`，否则 403 `csrf_origin_rejected`；
  - 无 `Origin` 但 `Sec-Fetch-Site: cross-site` 时同样 403；
  - 两者都没有时视为非浏览器客户端放行。
- `Settings` 启动校验：`BACKEND_CORS_ORIGINS` 含 `*` 时报错；`APP_ENV` 为 `production`/`prod` 且 `AUTH_COOKIE_SECURE=false` 时报错。

替代方案“双提交 CSRF token”需要前端引导接口、保存和重试逻辑，不采用。

### D4 密码哈希与策略

- 哈希使用 `argon2-cffi` 的 `PasswordHasher()` 默认参数（argon2id）；登录成功且 `check_needs_rehash` 为真时重新哈希；邮箱不存在时对固定 dummy hash 执行一次校验，使耗时接近。
- 邮箱：`strip().lower()`，长度 ≤254，匹配 `^[^@\s]+@[^@\s]+\.[^@\s]+$`。
- 显示名：`strip()` 后 1–100 字符。
- 密码：10–128 字符，至少 1 个字母和 1 个数字，不得等于邮箱或邮箱本地部分（不区分大小写）。前端镜像同一规则，以后端为准。

### D5 角色与权限

`app/core/permissions.py` 定义：

| 权限 | admin | member | viewer |
|---|---|---|---|
| `knowledge:read`（读取自己的资料、检索问答、核对引用） | ✓ | ✓ | ✓ |
| `knowledge:write`（上传、解析、重新分块、重新向量化） | ✓ | ✓ | ✗ |
| `users:manage`（用户管理） | ✓ | ✗ | ✗ |

- 依赖 `require_permission(perm)` 返回当前用户，缺权限时 403 `forbidden`，`detail` 说明缺少的操作权限。
- 公开注册只创建 `member`，请求体中的 `role` 等字段被忽略。
- 授权一律基于权限常量，不在业务代码中判断角色名。

### D6 API 契约

所有认证/授权错误统一为 `{"detail": "中文可读原因", "code": "<机器码>"}`，由 `AppError` 异常处理器输出；FastAPI 自身的 422 校验错误保留 `detail` 列表及 `loc/type/msg`，省略可能回显密码或完整请求体的 `input/ctx`。

| 方法与路径 | 权限 | 请求 | 成功响应 | 主要错误 |
|---|---|---|---|---|
| `POST /api/auth/register` | 公开 | `{display_name, email, password}` | 201 `UserRead` + Set-Cookie | 409 `email_taken`，422 `invalid_email`/`invalid_display_name`/`weak_password` |
| `POST /api/auth/login` | 公开 | `{email, password}` | 200 `UserRead` + Set-Cookie | 401 `invalid_credentials`，403 `account_disabled`，429 `too_many_attempts` + `Retry-After` |
| `POST /api/auth/logout` | 公开 | — | 204，撤销当前会话并清除 Cookie（幂等） | — |
| `GET /api/users/me` | 已登录 | — | 200 `UserRead` | 401 `auth_required` |
| `PATCH /api/users/me` | 已登录 | `{display_name}` | 200 `UserRead` | 422 `invalid_display_name` |
| `POST /api/users/me/password` | 已登录 | `{current_password, new_password}` | 204，撤销该用户全部会话并清除 Cookie | 400 `current_password_incorrect`，422 `weak_password` |
| `GET /api/admin/users?offset=0&limit=20` | `users:manage` | `limit` 1–100 | 200 `{items: UserRead[], total, offset, limit}`，按 `created_at` 升序，不含软删除用户 | 403 `forbidden` |
| `PATCH /api/admin/users/{id}` | `users:manage` | `{role?, status?}`，至少一项 | 200 `UserRead` | 404 `user_not_found`，409 `last_admin`/`cannot_disable_self`，422 `empty_update` |

- `UserRead` 保留原有 `id, display_name, email, avatar_url, status, deleted_at, created_at, updated_at`，新增 `role` 与按字母排序的 `permissions`；永不包含密码哈希、令牌或令牌哈希。
- 401 统一 `code=auth_required`，`detail` 区分“请先登录”与“登录已失效，请重新登录”。
- 原有业务接口：除 `/api/health` 与 `/api/auth/*` 外全部要求登录；读取与 `POST /api/search`、流水线验证要求 `knowledge:read`；`POST /api/uploads`、`POST /api/uploads/{id}/parse`、`POST /api/parsed-documents/{id}/rechunk`、`POST /api/document-chunk-jobs/{id}/re-embed` 要求 `knowledge:write`。跨用户资源继续返回与不存在一致的 404。原 503 “Current user is unavailable” 改为 401。
- 私有路由在 `api_router.include_router(..., dependencies=[Depends(get_current_user)])` 上统一挂认证，路由函数再通过 `CurrentUserDep`/`require_permission` 取得用户（同一请求内依赖缓存，只查一次库）。路由清单测试保证新增接口不会漏挂认证。

### D7 登录防爆破

进程内 `LoginRateLimiter`（时钟可注入）：同一规范化邮箱在 `AUTH_LOGIN_WINDOW_SECONDS=900` 内失败 `AUTH_LOGIN_MAX_FAILURES=5` 次后，窗口结束前的登录直接返回 429 `too_many_attempts` 和 `Retry-After`（秒），不校验密码；登录成功清零。未知邮箱同样计数。

### D8 管理员规则

- 有效管理员：`role='admin' AND status='active' AND deleted_at IS NULL`。
- 角色降级或禁用会使有效管理员数变为 0 时返回 409 `last_admin`；在同一事务中对有效管理员行 `SELECT ... FOR UPDATE` 后计数（PostgreSQL 生效，SQLite 测试只覆盖串行语义）。
- 管理员禁用自己返回 409 `cannot_disable_self`；在仍有其他有效管理员时允许自降级。
- 禁用用户时在同一事务内撤销其全部会话；重新启用不恢复旧会话。角色变更不撤销会话，下一次请求即按新角色授权。

### D9 检索、缓存与指纹隔离

- `compute_fingerprint(session, *, owner_user_id)` 只统计该用户向量数与该用户成功向量化任务的最近更新时间。
- `SearchService` 新增必填构造参数 `owner_user_id` 和可选 `kb_fingerprint`；缓存作用域 `scope = f"u:{owner_user_id}:{kb_fingerprint}"`。
  - 搜索响应 L1 会话键：显式 `session_id` 或 history 摘要存在时为 `f"{scope}:{sid}"`，两者都没有时仍跳过响应 L1。
  - `_count_total_embeddings` 与 `_vector_search` 同时按 `DocumentEmbedding/ParsedDocument/UploadedFile.owner_user_id` 过滤，并排除已软删除上传。
- `QueryRewriter.rewrite` 新增关键字参数 `cache_namespace`；`SearchService` 始终传入 `scope`，`session_id` 仍传未加前缀的会话标识。重写器自行把 namespace 加到 L1 会话键、在途去重键和不满意检测键；L2 键变为 `l2:{namespace}:{normalized}`。未传 namespace 的直接调用保持原行为。
- 路由不再调用 `update_fingerprint`；共享实例指纹保持 `None`，过期判断由键中的指纹完成，从而消除并发覆盖。
- 上传后的主动失效保持现状（清空 L1）；由于指纹已进入缓存键，旧条目即使未被清除也不会再被命中。

### D10 旧默认用户与 CLI

- 迁移不改动旧资料和默认用户；默认用户没有凭据，无法登录，也不会被注册者继承。
- `uv run python -m app.cli create-admin --email E --display-name N [--claim-legacy-user] [--password-stdin]`：
  - 默认创建新的管理员；
  - `--claim-legacy-user` 把默认用户（存在、未软删除、无凭据）认领为管理员：写入邮箱、显示名、`role=admin` 和凭据，旧资料原样归属该账号；
  - 密码通过 `getpass` 输入两次，或用 `--password-stdin` 读取一行，不接受命令行参数；
  - 退出码：0 成功，1 输入或策略校验失败，2 前置条件不满足（邮箱已存在、默认用户不可认领等）。
- `uv run python -m app.cli reset-password --email E [--password-stdin]`：重置密码并撤销该用户全部会话。

### D11 前端

- `api/client.ts`：新增 `ApiError{status, code, detail}`、`apiFetch`（`credentials: "include"`、`X-Trace-ID`、非 `/auth/*` 请求遇 401 调用 `setUnauthorizedHandler` 注册的回调）、`apiPostJson`、`apiPatchJson`；`apiGet`/`apiPostForm` 改为基于 `apiFetch`。`search`、`documentParsing`、`documentChunking`、`embedding` 改用 `apiFetch`；`src/api` 中除 `client.ts` 外不得直接调用 `fetch(`。
- 新增 `api/auth.ts`、`api/adminUsers.ts`；`api/users.ts` 增加 `role`、`permissions`、`updateMyProfile`、`changeMyPassword`。
- `stores/user.ts`：`status: "unknown"|"authenticated"|"anonymous"|"error"`、`currentUser`、`userError`；`ensureSession()` 单飞；`login/register/logout/updateProfile/changePassword/handleUnauthorized`；`hasPermission(perm)`。认证后调用 `chat.bindUser(user.id)`，退出或失效时 `chat.bindUser(null)`。
- `stores/chat.ts`：初始为空；`bindUser(id)` 从 `knowra:chat:v2:{id}` 加载；仅当 `id` 为旧默认用户且新键不存在时迁移旧 `knowra:chat`；其他账号绝不读取旧键。账号切换后旧请求的 `updateBubble` 找不到对话即被忽略。
- 路由：`/login`、`/register`（`guestOnly`），`/`、`/verify`、`/account`（`requiresAuth`），`/admin/users`（`requiresAuth` + `permission: "users:manage"`，无权限时页面显示权限不足且不请求列表）。`beforeEach` 先 `await ensureSession()`，匿名访问私有页跳 `/login?redirect=<安全站内路径>`。`sanitizeRedirect` 拒绝非 `/` 开头、`//`、反斜线、控制字符、`/login`/`/register` 等路径。
- 跨标签页：退出时写入 `localStorage["knowra:auth:logout"]`，其他标签页监听 `storage` 事件执行 `handleUnauthorized`。
- 页面沿用 paper/surface/ink/line/brand 令牌，表单使用 label、`autocomplete`、`role="alert"` 错误与 `uniqueId()`；输入框 `text-base`，移动端 320px 无横向滚动。只读用户的附件按钮禁用并显示“只读账号不能上传或处理资料”。侧栏用户区提供账户设置、用户管理（仅管理员）与退出登录。

## Risks / Trade-offs

- [限流按进程计数，多 worker 时阈值放大] → 文档说明；`LoginRateLimiter` 接口可替换为共享存储实现。
- [账号级锁定可被他人触发，导致 15 分钟内无法登录] → 接受；后续加入 IP 维度限流。
- [注册返回 409 暴露邮箱是否已注册] → 无邮件验证时接受。
- [末位管理员并发保护仅在 PostgreSQL 生效] → SQLite 单测覆盖串行语义，PostgreSQL 依赖 `FOR UPDATE`。
- [对话历史仍明文保存在本机 localStorage] → 已按用户分键且界面不可见；服务端同步作为后续变更。
- [回滚到旧代码会恢复默认用户旁路] → 回滚期间必须关闭外部访问。

## Migration Plan

1. 备份 PostgreSQL 与 `storage/`。
2. `uv run alembic upgrade head`：新增 `users.role`、`user_credentials`、`user_sessions`。此后所有私有接口返回 401，旧数据不暴露。
3. `uv run python -m app.cli create-admin --email you@example.com --display-name 你的名字 --claim-legacy-user` 认领旧资料并成为管理员；或不带参数创建全新管理员。
4. 启动前后端，登录验证。
5. 回滚：先停止外部访问，在当前迁移文件仍可用时执行 `uv run alembic downgrade -1`，再恢复旧代码；凭据与会话丢失，用户行和资源归属保留。

## Open Questions

无。注册开关、IP 限流、管理员筛选等已列入非目标。

## 采纳说明

| Opus 方案点 | 处理 | 理由 |
|---|---|---|
| 凭据独立表（第一轮）vs `users.password_hash`（第二轮） | 采纳独立表 | 与归档决策一致 |
| 角色仅 admin/member（第一轮）vs 三角色（第二轮） | 采纳三角色 | proposal 与 spec 已确定 viewer 只读语义，满足角色权限划分需求 |
| 双提交 CSRF token（第二轮）vs Origin 校验（第一轮） | 采纳 Origin 校验 | 前端无需令牌管理，配合 SameSite=Lax 足够 |
| 会话空闲超时、记住我、`last_seen_at` | 不采纳 | 非本轮必需，绝对过期 + 撤销已满足 |
| 账号锁定存数据库（第一轮）vs 进程内限流（第二轮） | 采纳进程内按邮箱限流 | 无需新增列；多进程局限已记录 |
| IP 与注册限流、常见密码表、注册开关、`/auth/options` | 不采纳 | 未在需求中，列入非目标 |
| 改密后签发新会话（第一轮）vs 撤销全部会话要求重新登录（第二轮） | 采纳后者 | 与 `user-account-ui` 规格一致，实现更简单 |
| 旧数据迁移到新账号（第二轮 claim）vs 认领默认用户行（第一轮） | 采纳认领默认用户行，且需显式 `--claim-legacy-user` | 不搬迁数据，满足“显式认领” |
| 指纹逐请求传参、缓存命名空间 | 采纳 | 消除跨用户命中与全局指纹竞争 |
| 前端 identityEpoch + AbortController 注册表 | 不采纳 | 对话存储按用户绑定后，迟到响应找不到对话即被忽略；页面切换会卸载组件内状态 |

## 验收适配说明

- SQLite 测试模型的上传去重索引补齐 `sqlite_where=deleted_at IS NULL`，与已有 PostgreSQL 部分唯一索引保持一致；既有强制替换测试驱动此修复。隔离测试的多份种子资料使用独立内容，避免在测试准备阶段触发合法的去重约束。
- 搜索响应缓存须支持未启用重写时的 `rewrite_info=null`，保持既有接口契约。


- 会话探测的网络/服务错误使用 `error` 状态，提供重试入口；私有视图仅在认证成功后挂载，并按用户 ID 重建，避免退出或换号后保留组件局部状态。
- 422 校验错误只返回 `loc/type/msg`，避免字段类型错误或缺字段时回显密码；新增六个错误输入用例先确认 RED，再修复处理器。
- 320px 用户管理卡片将账户信息与操作控件分行；浏览器宽度断言先确认原信息区只有 62px，再修复并验证完整可读行。
- 原基础用户规范中的默认身份与禁止认证入口已由新增认证要求取代；delta 使用显式 REMOVED/ADDED 并说明迁移方式，避免归档时隐式丢弃旧场景。语义搜索明确区分服务层空结果与现有 HTTP 404 约定。
