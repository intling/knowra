# 后台管理交付验证

验证日期：2026-10-22。实现变更：`add-admin-console`。用户对红测试评审回复“继续”后完成 GREEN、回归和联调。工作区原有认证、演示额度等未提交改动保留，未提交代码、未操作生产数据库。

## 自动验证

| 验证 | 实际结果 | 证据 |
| --- | --- | --- |
| `cd backend && uv run pytest -q --tb=short` | 1233 passed, 9 skipped | [backend-all.txt](validation/backend-all.txt) |
| 独立 PostgreSQL 并发测试 | 4 passed | [postgres-concurrency.txt](validation/postgres-concurrency.txt) |
| `cd front && npm run lint` | 通过 | [frontend-lint.txt](validation/frontend-lint.txt) |
| `cd front && npm run test` | 53 files, 628 passed | [frontend-all.txt](validation/frontend-all.txt) |
| `cd front && npm run build` | vue-tsc 与 Vite 构建通过 | [frontend-build.txt](validation/frontend-build.txt) |
| 本次后台功能涉及文件 Ruff | check 和 format 均通过 | [changed-ruff.txt](validation/changed-ruff.txt)、[changed-format.txt](validation/changed-format.txt) |
| 全仓 `uv run ruff check .` | 39 项既有告警，来自未由本变更修改的旧迁移、postprocessor、uploads、历史测试文件 | [backend-ruff.txt](validation/backend-ruff.txt) |
| 全仓 `uv run ruff format --check .` | 6 个既有文件需格式化 | [backend-format.txt](validation/backend-format.txt) |
| `openspec validate add-admin-console --strict` | 通过 | [openspec.txt](validation/openspec.txt) |
| `git diff --check` | 通过 | 执行无输出、退出码 0 |

全仓静态检查的旧问题未批量改写，避免混入与后台无关的变更。本次新建/修改的后台实现与新增测试已独立通过 Ruff。全量 pytest 的 9 个跳过中包含 4 个需要独立 PostgreSQL 环境的并发测试；这 4 项已使用测试数据库单独执行并通过。

## TDD 与运行时覆盖

初始 100 项红测试及既有回归基线见 [red-tests.md](red-tests.md)。追加测试先失败后实现：数据库迁移、真实搜索依赖、自动向量化、任务快照、本地无密钥模型、客户端释放、环境向量化关闭时的后台绑定和受管模型覆盖保护。对应 RED/GREEN 输出保存在 `validation/`。

PostgreSQL 的真实向量任务 INSERT 并发测试暴露管理员 `FOR UPDATE` 与外键 `KEY SHARE`/模型绑定锁的交叉死锁。先保存 [postgres-admission-red.txt](validation/postgres-admission-red.txt)，再改为不阻塞外键引用的 `FOR NO KEY UPDATE`，保持共同 advisory lock 与管理员存续约束；最终 4 项并发测试通过。

搜索每请求读取一次有效配置副本；自动向量化与重新向量化持绑定锁捕获配置，任务拥有独立 session。缓存/请求去重保留用户边界并附加配置版本。模型客户端在请求、任务或改写调用结束时关闭，临时超时客户端也在失败后释放。模型密钥不写入响应、日志和任务 JSON。

## PostgreSQL 迁移与并发

使用独立 `pgvector/pgvector:pg18` 临时容器，端口 15479。执行 upgrade、downgrade 到 `20261021_0002`、再次 upgrade；核对账号、凭据、会话、上传、解析、分块、向量作业及向量的数量保留，并确认四种用途空绑定。

迁移详情见 [postgres-migration-roundtrip.txt](validation/postgres-migration-roundtrip.txt)。并发测试每例创建独立临时 schema 并清理，覆盖双管理员自行降级、相互删除及撤销会话、同用途同时激活、任务入队与 Embedding 切换。通过 `ADMIN_TEST_DATABASE_URL` 显式启用，不连接默认数据库。

## 浏览器联调

独立后端 15480、前端 15481、临时测试账号；Chromium + Playwright 连接真实 API。未请求外部模型服务。完整结果见 [browser.txt](validation/browser.txt)。

- 建号后使用初始密码登录，成员访问管理页面显示权限提示，管理 API 返回 403。
- 重置后旧会话和旧密码失效，新密码可登录；禁用撤销会话，启用后可登录，角色修改实际返回只读权限。
- 确认删除后账号失效并从列表消失；确认框 Tab 保持焦点、Esc 关闭并归还触发按钮。
- 四用途创建并逐一激活；编辑不回显密钥，留空保留；恢复环境、禁用、删除正常。
- 1440px 和 320px 页面无横向溢出，控制台无运行时异常。
- 测试服务最初手写了格式不正确的主密钥，页面正确显示 503 原因；改用标准 Fernet key 后全部流程通过。

截图：[用户桌面](browser/users-desktop.png)、[用户 320px](browser/users-mobile.png)、[模型桌面](browser/models-desktop.png)、[模型 320px](browser/models-mobile.png)、[向量配置 320px](browser/models-mobile-form.png)。

## 使用与边界

管理员从账户菜单“后台管理”或 `/admin` 进入。启动更新版本前执行迁移，并按 [后端说明](../../../../backend/README.md#model-administration) 设置和独立备份 `MODEL_CONFIG_ENCRYPTION_KEY`。默认绑定仅影响后续请求；未绑定时沿用环境配置。首版使用固定角色和 2560 维向量，已有索引或未完成任务时拒绝变更空间，不自动重建索引。管理员不读取他人的私有资料，用户删除只做软删除。

## 当前账号改密入口样式修复（2026-10-22）

用户反馈“修改我的密码”入口与相邻操作样式不一致。该入口仅设置文字样式，缺少按钮边框和内边距；修复为复用 `account-secondary`，保留 RouterLink 的 `/account` 导航。

使用本地 Vite 15581 与 Chromium，拦截 API 返回虚构管理员/成员数据，不连接生产 API 或数据库。修复前先运行浏览器断言：1440px、390px、320px 均因缺少按钮边框失败；改密入口高度为 20px、边框 0px、内边距 0，相邻按钮高度为 38px、边框 1px、上下/左右内边距为 8px/16px。

修复后同一组浏览器断言全部通过：入口高度 38px、边框 1px、圆角 8px、内边距和字重与相邻按钮一致；桌面同一行底部对齐，390px 和 320px 无横向溢出。鼠标点击和键盘 Enter 均进入 `/account`，无浏览器运行异常；桌面和 320px 截图已人工复核。

本次实际验证：`npm run lint` 通过；`npm run test` 为 53 文件、628 项通过；`npm run build` 通过；`openspec validate add-admin-console --strict` 与 `git diff --check` 通过。本次仅修改仓库前端与相关工件，未发布生产服务。
