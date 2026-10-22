## 1. 设计与基线

- [x] 1.1 记录变更前前后端测试基线（`evidence/baseline.md`）
- [x] 1.2 由 `pi` 的 `dtmaas/claude-opus-5-5` 产出设计，保存原文并在 `design.md` 记录采纳说明
- [x] 1.3 补齐 `user-authentication` 规格、`design.md` 与本任务清单

## 2. 后端红测试（先确认 RED，评审通过后再实现）

- [x] 2.1 密码策略、邮箱/显示名规范化、argon2id 哈希与登录限流单测
- [x] 2.2 会话服务单测：只存哈希、过期、撤销、禁用/软删除用户失效
- [x] 2.3 认证 API：注册、登录、退出、Cookie 属性、错误码、限流、来源校验、秘密不外泄
- [x] 2.4 账户 API：`/users/me` 新字段、资料修改、改密撤销全部会话、当前密码错误返回 400
- [x] 2.5 管理员 API：403、分页、角色变更即时生效、禁用/启用、末位管理员与禁用自己
- [x] 2.6 授权与隔离：路由清单 401、只读用户写接口 403 且无副作用、跨用户资源 404
- [x] 2.7 检索隔离：按用户计数与过滤、指纹按用户、缓存命名空间、路由不再写全局指纹
- [x] 2.8 CLI：创建管理员、认领旧默认用户、密码输入方式与退出码、重置密码
- [x] 2.9 迁移与配置：新列/新表结构、downgrade、CORS `*` 与生产非 Secure Cookie 启动失败
- [x] 2.10 既有测试迁移到新契约：认证依赖覆盖、503→401、`SearchService`/`compute_fingerprint` 新参数

## 3. 前端红测试

- [x] 3.1 API client：`ApiError`、`credentials`、401 回调、JSON 写方法；`src/api` 禁止直接 `fetch(`
- [x] 3.2 `auth`、`users`、`adminUsers` API 模块
- [x] 3.3 `sanitizeRedirect` 与密码策略工具
- [x] 3.4 user store 状态机与 chat store 按用户隔离、旧键迁移、迟到响应忽略
- [x] 3.5 路由守卫与路由表
- [x] 3.6 登录、注册、账户、用户管理页面与侧栏账户入口、只读用户上传禁用

## 4. 后端实现

- [x] 4.1 依赖 `argon2-cffi`；模型 `User.role`、`UserCredential`、`UserSession` 与 Alembic 迁移
- [x] 4.2 `core/errors.py`、`core/permissions.py`、配置项与启动校验
- [x] 4.3 `services/passwords.py`、`services/auth.py`（会话、限流、注册登录、改密）、`services/user_admin.py`
- [x] 4.4 `api/deps.py` 认证/权限/来源依赖；`auth`、`users`、`admin_users` 路由；`router.py` 统一挂认证
- [x] 4.5 既有资料路由切换到新依赖与 `knowledge:write`，删除默认用户解析
- [x] 4.6 检索、查询重写、缓存与指纹按用户隔离
- [x] 4.7 `app/cli.py` 管理命令

## 5. 前端实现

- [x] 5.1 API client 与各 API 模块
- [x] 5.2 user/chat store 与跨标签页退出
- [x] 5.3 路由守卫、`main.ts` 401 处理
- [x] 5.4 登录、注册、账户、用户管理页面，侧栏账户菜单与只读禁用说明

## 6. 文档与验收

- [x] 6.1 更新 `.env.example`、根/前后端 README 与 AGENTS 章程
- [x] 6.2 后端 `ruff check`、`ruff format --check`、`pytest` 与 Alembic upgrade/downgrade/upgrade（变更文件 Ruff 通过；全库既有失败详见验收证据）
- [x] 6.3 前端 `lint`、`test`、`build`
- [x] 6.4 本地浏览器验证：注册、登录、上传、提问、退出、换账号隔离、只读与管理员流程、320px 移动端
- [x] 6.5 汇总验收证据到 `evidence/`
