# 用户体系最终验收

执行日期：2026-10-21。沿用本变更已有 RED 测试继续实现，新增边界问题也先运行失败测试再修复。原基线见 [baseline.md](baseline.md)，原用户体系红测试见 [red-tests.md](red-tests.md)。

## 自动化验证

| 范围 | 命令与实际结果 |
|---|---|
| 后端全量 | 在 `backend` 执行 `DATABASE_URL=postgresql+psycopg://knowra@127.0.0.1:15439/knowra uv run pytest -q --tb=line`：**1089 passed, 4 skipped**，23.10s |
| 前端全量 | 在 `front` 执行 `npm run test`：**50 files, 584 tests passed**，20.14s |
| 前端 lint | `npm run lint`：通过，退出码 0 |
| 前端构建 | `npm run build`：通过；vue-tsc 与 Vite 构建成功，118 modules |
| 后端变更文件 | 对 `git diff --name-only` 与新增文件列表内全部现存 Python 文件执行 Ruff：**58 files**，`ruff check` 全通过，`ruff format --check` 全通过 |
| 后端全库检查 | `uv run ruff check .`：**46 项既有错误**；`uv run ruff format --check .`：**7 个既有文件待格式化**。这些文件均未修改；逐一对比 `git show HEAD:backend/<path>` 确认内容相同 |
| OpenSpec | `npx --yes @fission-ai/openspec validate add-user-auth-rbac --strict`：通过 |
| 补丁完整性 | `git diff --check`：通过 |

命令输出保存在 [validation/](validation/)。4 项跳过来自原有 L2 相似度阈值测试组：向量语义检索尚未启用，基线也跳过这 4 项。

全库 Ruff 失败集中在未修改的旧迁移、chat_adapter、postprocessor、uploads 和旧查询重写测试；未通过忽略规则或扩大无关格式化掩盖问题。本次改动文件的静态检查通过，但不声明整个仓库门禁全绿。

原基线三个失败已逐项复核：两项后台作业测试需要可连接的 PostgreSQL，本次使用隔离数据库后通过；SQLite 的强制替换失败来自部分唯一索引缺少 SQLite 条件，先确认旧失败，再补齐与 PostgreSQL 一致的 `sqlite_where` 后通过。

## 补充的 Red → Green

- 私有视图会话边界：新增 `front/src/__tests__/App-session.spec.ts`，先得到 **3 failed, 1 passed**，实现未认证不挂载、错误可重试、按用户 ID 重建后 **4 passed**。
- 校验错误秘密回显：注册、登录、改密各覆盖非法字段类型和损坏 JSON，先得到 **6 failed**；422 处理器保留 `loc/type/msg` 并移除 `input/ctx` 后，这 6 项通过，认证 API 文件 **31 passed**。
- 320px 用户管理可读性：真实浏览器断言账户信息宽度至少为卡片宽度减 48px；原卡片 286px，信息区只有 **62px**，断言失败。改成窄屏上下分行后通过。具体失败与成功输出见 `validation/mobile-layout-{red,green}.txt`。

## PostgreSQL 与迁移

使用专用临时 `pgvector/pgvector:pg18` 容器，名称 `knowra-auth-verification-20261021`，仅绑定 `127.0.0.1:15439`；未改动现有容器或真实数据库。

1. 空库执行 `alembic upgrade head`，经过全部历史迁移到 `20261021_0001`，成功。
2. 执行 `downgrade -1 → upgrade head`，成功；默认用户 UUID 保留，认领前没有凭据。
3. CLI 显式认领旧默认用户为管理员；真实 API 登录成功。普通注册返回 201、角色 member，与默认 UUID 不同。
4. CLI 创建独立管理员，随后重置密码：旧会话请求返回 401，旧密码登录 401，新密码登录 200。
5. 使用真实 pgvector 查询两位用户的 2/3 条向量：各自的 `total_searched`、片段和引用仅属于自己；复用相同 query/session_id 时缓存仍隔离，同用户重试能命中；他人新增资料不改变自己的指纹。仅向量与生成适配器使用固定结果，SQL 在真实 PostgreSQL 执行。
6. 已有资料下再次执行 `downgrade -1 → upgrade head`：逐行比较用户身份、上传与解析资料外键，前后完全一致；回滚删除凭据/会话/role，新升级恢复 member 且凭据和会话为空，符合回滚契约。行数与结果见 `validation/migration-preservation.txt`。

## 浏览器流程

使用 Chromium 与 Playwright，本地 Vite 代理实际 FastAPI 和上述 PostgreSQL；未 mock 身份、会话、角色或资料 API。为隔离验收环境，关闭模型 bootstrap、自动分块、文档 embedding 和 query rewrite，查询向量使用本地固定向量 HTTP 服务。上传经过真实文本解析；提问验证的是空知识库的实际 404 提示，未声称验证外部模型回答质量。

已通过：

- 匿名私有路由回到登录；注册自动登录，Cookie 为 HttpOnly、SameSite=Lax、Path=/api。
- 成员上传成功；提问显示空知识库说明。
- 修改显示名、修改密码，全部旧会话撤销，仅新密码可登录。
- 同一浏览器两个标签页退出同步。
- 甲/乙账号对话分别保存；切回甲恢复甲的历史，乙的内容不可见。
- 管理员变更角色需要确认；末位有效管理员不能降权；只读账号界面禁上传，直接写 API 也返回 403。
- 禁用立即使旧 Cookie 返回 401；重新启用后旧 Cookie 仍无效，需要重新登录。
- 320px 登录、注册、工作台、账户、用户管理无横向溢出；通过移动导航打开账户页面；用户管理账户信息保持可读整行。
- 桌面主流程无未捕获浏览器异常。

截图：[登录](browser/login-desktop.png)、[成员对话](browser/member-chat.png)、[只读](browser/viewer-chat.png)、[管理页](browser/admin-desktop.png)、[320px 账户](browser/account-mobile-320.png)、[320px 管理页](browser/admin-mobile-320.png)。流程输出见 [browser/results.json](browser/results.json)。

## 交付边界

代码、配置模板、三份 README 与三份 AGENTS 已同步。登录限流仍为设计约定的进程内实现；团队共享、邮件验证、自助找回密码不在本变更范围。未自动归档、提交或部署，真实环境迁移和管理员初始化按 README 执行。验收专用服务和临时数据库在验收后清理。
