## 1. 后端契约测试

- [x] 1.1 新增 `GET /api/users/me` 成功场景 API 测试，先确认因路由或实现缺失而 RED。
- [x] 1.2 新增当前用户不可用场景 API 测试，覆盖默认用户不存在、禁用或软删除时返回非 2xx 与可诊断错误。
- [x] 1.3 新增用户服务测试，覆盖可解析 active 且未软删除的默认用户。
- [x] 1.4 新增软删除服务测试，覆盖 `deleted_at` 非空用户不会被当前用户解析返回。
- [x] 1.5 新增模型或迁移结构测试，覆盖 `users` 表字段、邮箱非空唯一语义和 `deleted_at` 字段。

## 2. 后端实现

- [x] 2.1 新增 `backend/app/models/user.py`，定义 `User` SQLModel 表模型和基础字段。
- [x] 2.2 更新 `backend/app/models/base.py`，导入用户模型以供 Alembic metadata 发现。
- [x] 2.3 新增 Alembic migration，创建 `users` 表、主键、必要索引、非空约束和邮箱唯一约束。
- [x] 2.4 新增用户 schema，定义 `GET /api/users/me` 响应结构。
- [x] 2.5 新增用户服务，提供默认用户查询和当前用户解析，默认排除 `deleted_at` 非空和非 active 用户。
- [x] 2.6 新增 `backend/app/api/routes/users.py`，实现 `GET /api/users/me`。
- [x] 2.7 更新 `backend/app/api/router.py`，挂载 users 路由到 `/api` 前缀下。
- [x] 2.8 明确默认用户初始化方式，并在测试 fixture、迁移或初始化服务中提供可验证默认用户。

## 3. 前端契约测试

- [x] 3.1 新增 `getCurrentUser()` API 测试，先确认因封装缺失而 RED。
- [x] 3.2 新增 user store 成功场景测试，覆盖加载完成后保存当前用户。
- [x] 3.3 新增 user store 失败场景测试，覆盖请求失败时保存错误状态。
- [x] 3.4 新增前端展示测试或组件测试，确认当前用户上下文可见且没有登录、注册、退出或用户切换入口。

## 4. 前端实现

- [x] 4.1 新增 `front/src/api/users.ts`，定义用户响应类型和 `getCurrentUser()`，复用现有 API client。
- [x] 4.2 新增 `front/src/stores/user.ts`，维护 `currentUser`、`isLoading`、`error` 和 `loadCurrentUser()`。
- [x] 4.3 在现有页面或应用壳层加载当前用户，并展示用户名称、加载中和加载失败状态。
- [x] 4.4 确认前端普通用户流程不暴露 `owner_user_id` 输入，也不提供认证入口。

## 5. 文档与验证

- [x] 5.1 如启动、API 契约或目录结构说明发生变化，更新 `backend/README.md`、`front/README.md` 或根目录 `README.md`。
- [x] 5.2 运行后端验证：`uv run ruff check .`、`uv run ruff format --check .`、`uv run pytest`。
- [x] 5.3 运行前端验证：`npm run lint`、`npm run test`、`npm run build`。
- [x] 5.4 如数据库可用，执行 Alembic upgrade 验证 `users` 表迁移可应用。
- [x] 5.5 进行本地 API 或浏览器 smoke check，确认 `GET /api/users/me` 和前端当前用户展示可用。
