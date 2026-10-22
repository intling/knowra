# 红测试证据（RED）

执行日期：2026-10-20。以下结果在**未修改任何生产代码**的前提下取得，所有失败均来自尚未实现的模块、参数或行为。

## 后端

命令：`cd backend && uv run pytest -q -p no:cacheprovider --continue-on-collection-errors -rfE --tb=line`

结果：`128 failed, 797 passed, 4 skipped, 27 errors`

| 失败原因 | 说明 |
| --- | --- |
| `ModuleNotFoundError: app.api.deps` / `app.services.auth` / `app.core.errors` | 认证依赖、会话服务、统一错误尚未实现；既有资料接口测试已改为通过 `authenticate_as` 覆盖认证依赖 |
| `ModuleNotFoundError: argon2` | 密码哈希依赖尚未加入 |
| `ImportError: UserCredential / UserSession` | 凭据表与会话表模型尚未实现 |
| `TypeError`：`SearchService(owner_user_id=…)`、`compute_fingerprint(owner_user_id=…)`、`QueryRewriter.rewrite(cache_namespace=…)`、`CacheManager.store_l2(namespace=…)` | 检索与缓存按用户隔离的新参数尚未实现 |
| `assert 503 == 401`、`assert 200 == 401` | 现有实现仍回退默认用户或返回 503，新契约要求 401 |
| 用户表字段断言缺少 `role` | `users.role` 尚未实现 |
| 3 个 teardown `SimpleNamespace.begin` | 关机状态用例在导入失败后未执行 finally 清理，是上述 ImportError 的连带失败 |

既有失败复核：`test_post_rechunk_returns_202_and_created_job`、`test_post_uploads_returns_created_record_and_stores_file`（后台任务连接真实 PostgreSQL 失败）、`test_create_upload_force_replaces_duplicate` 与基线一致，不属于本变更。

## 前端

命令：`cd front && npx vitest run --reporter=json`

结果：`72 failed, 418 passed`（20 个测试文件失败）

| 失败原因 | 说明 |
| --- | --- |
| `Failed to resolve import`：`api/auth`、`api/adminUsers`、`shared/auth/*`、`router/guards`、`views/LoginView` 等 | 新模块与页面尚未实现 |
| `store.bindUser is not a function`（51） | chat store 尚未按用户绑定存储；既有持久化用例已改为绑定测试用户 |
| `setUnauthorizedHandler/apiPostJson/apiPatchJson is not a function`、缺少 `credentials` | 统一 API client 尚未实现 |
| 路由表断言 | 登录、注册、账户、用户管理路由与守卫尚未实现 |
| `no-direct-fetch` | `search/documentParsing/documentChunking/embedding` 仍直接调用 `fetch(` |
| 只读上传入口 | `ChatInput`/`WelcomeView` 尚无 `canUpload` |

## 既有测试的契约迁移

- 后端：资料接口测试的 `seed_current_user` 同时 `authenticate_as(user)`；“当前用户不可用 503”改为“未登录 401”；`SearchService`、`compute_fingerprint` 补 `owner_user_id`；重写调用断言补 `cache_namespace`；`tests/api/test_users.py` 改为“不回退默认用户”；删除只覆盖已移除默认用户解析器的 `tests/services/test_user_service.py`（语义由 `tests/auth/test_auth_sessions.py` 覆盖）；`tests/conftest.py` 新增低成本 argon2、`auth_db`、`auth_client` fixture。
- 前端：`users/health` 调用断言补 `credentials: "include"`；`chat.test.ts` 绑定测试用户后读写 `knowra:chat:v2:<id>`；`user.test.ts` 按新状态机重写；路由表断言更新为 8 条；`ChatArea.spec.ts` 挂载前种下成员用户。
