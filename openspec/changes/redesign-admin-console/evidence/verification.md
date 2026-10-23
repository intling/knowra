# 后台管理改版交付与验证

验证日期：2026-10-22。变更：`redesign-admin-console`。实施与本地验收完成，未部署至线上。

## 交付内容

- 六页独立后台：运行总览、用户管理、模型服务、处理任务、操作审计、系统状态。`/admin` 进入总览，原用户/模型直达地址保留；桌面侧栏、窄屏导航与详情抽屉沿用现有语义令牌。
- 用户管理：全量服务端字面搜索、组合筛选、详情、最近 60 分钟额度查看/调整、撤销他人有效会话。保留账号存续、软删除、会话失效及资料归属规则。删除精确匹配邮箱，无邮箱旧账号匹配完整 UUID。
- 模型管理：四用途生效来源、配置/绑定独立版本、显式有界协议测试、15 分钟自动过期标记。保存、测试与默认切换独立；Embedding 空间保护保持。
- 运行读取：三阶段全部实际任务尝试、安全错误投影、准确上传关联；总览明确统计口径，系统诊断标明单实例范围、截止时间和未知状态。
- 审计：账号/额度/会话/模型写操作与成功事件原子提交；执行过的模型测试结果与结果审计同提交。查询二次白名单投影，支持动作、结果、操作者、时间与 trace 筛选。
- 文档：根 README、两端 README/AGENTS 与后端环境模板同步，包含权限、接口、额度语义、诊断限制、主密钥备份与发布回退步骤。

补充回归已验证筛选不匹配时创建成功说明、创建中的重复提交拦截、详情切换拒绝旧对象响应，以及用户目录刷新失败保留并标记旧数据；见 [frontend-user-edge-regression.txt](frontend-user-edge-regression.txt)。

## 最终验证

| 命令或场景 | 实际结果 | 原始证据 |
|---|---|---|
| `uv run --no-sync pytest -q --tb=short`，启用隔离 PostgreSQL 并发环境变量 | 1,489 passed，4 skipped，72.03 秒 | [backend-tests.txt](backend-tests.txt) |
| `npm run test` | 652 passed，58 files，32.73 秒 | [frontend-tests.txt](frontend-tests.txt) |
| `npm run lint` | 通过，退出码 0 | [frontend-lint.txt](frontend-lint.txt) |
| `npm run build` | TypeScript 与 Vite 构建通过，144 modules | [frontend-build.txt](frontend-build.txt) |
| `uv run --no-sync ruff check .` | 39 项既有问题，均位于未修改的 9 个文件，与基线一致 | [ruff-final-all.txt](ruff-final-all.txt) |
| `uv run --no-sync ruff format --check .` | 6 个既有文件需格式化，本次未改动这些文件 | [format-final-all.txt](format-final-all.txt) |
| Ruff 检查及格式检查本次全部 38 个 Python 文件 | 两项均通过，退出码 0 | [ruff-final-changed.txt](ruff-final-changed.txt)、[format-final-changed.txt](format-final-changed.txt) |
| `openspec validate redesign-admin-console --strict --no-interactive` | 通过 | [openspec-validate.txt](openspec-validate.txt) |
| Chromium + Vite + Uvicorn + 真实 PostgreSQL 浏览器流程 | 16 组检查通过，0 未处理页面异常 | [browser-report.json](browser-report.json)、[browser-run.txt](browser-run.txt) |
| 旧前端生产构建与真实浏览器回退 | 4 组检查通过 | [rollback-build.txt](rollback-build.txt)、[rollback-report.json](rollback-report.json) |

四项跳过属于既有 `test_semantic_cache_l2.py` 中等待向量语义检索实现的相似度阈值场景；本次后台 PostgreSQL 并发场景已实际运行。全仓 Ruff 不是全绿，不将既有静态问题隐藏为通过，也未顺带修改无关文件。

## 需求、RED 与 GREEN 映射

| 能力 | RED 证据 | 当前自动化及浏览器覆盖 |
|---|---|---|
| 数据增量与保留 | [data-red-review.md](data-red-review.md)、[data-red.txt](data-red.txt) | `test_operations_schema.py`、`test_operations_migration.py`；真实 upgrade/downgrade/upgrade 逐行对比 15 张旧表、19 条旧记录及非空 2560 维向量 |
| 事务审计 | [audit-red-review.md](audit-red-review.md)、[audit-red.txt](audit-red.txt) | `test_audit_transactions.py`、`test_postgres_concurrency.py`；成功原子提交、审计故障回滚、拒绝留痕、同 trace 独立操作、最后管理员并发 |
| 用户搜索和详情 | [user-directory-red-review.md](user-directory-red-review.md) | `test_user_directory.py` 50 项；字面通配符、原始字符上限、全量分页、只读详情、401/403与秘密隔离 |
| 额度与会话 | [account-controls-red.txt](account-controls-red.txt)、[quota-concurrency-red.txt](quota-concurrency-red.txt) | `test_account_controls.py` 与真实 PostgreSQL 并发；不存在限额行、收紧/放宽/移除、预留保留、提交前失权、取消/重复撤销、自身保护 |
| 壳层与用户交互 | [frontend-users-red.txt](frontend-users-red.txt) | `AdminWorkspace.spec.ts`、`AdminUserControls.spec.ts`、原生命周期/路由/确认框回归；300ms 防抖、筛选竞态、详情、取消、焦点与秘密清理 |
| 模型生效与诊断 | [effective-models-red.txt](effective-models-red.txt)、[model-probes-red.txt](model-probes-red.txt)、[model-probes-lifecycle-red.txt](model-probes-lifecycle-red.txt) | `test_effective_models.py`、`test_model_probes.py`、`test_probe_transport.py`；四协议、跨 worker 冷却/并发、租约、超时、DNS 实际连接、删除保留、原子结果审计 |
| 模型页面 | [frontend-models-red.txt](frontend-models-red.txt)、[frontend-probe-expiry-red.txt](frontend-probe-expiry-red.txt) | `AdminModelDiagnostics.spec.ts`；四卡片、固定样例费用确认、测试不激活、版本冲突、持续停留自动过期且不重测 |
| 运行、系统、审计读取 | [operational-reads-red.txt](operational-reads-red.txt)、[system-budget-red.txt](system-budget-red.txt) | `test_operational_reads.py`；安全 UNION、UTC 半开窗口、准确关联、局部失败、2/5 秒期限、权限与无模型调用 |
| 运行页面与 API client | [frontend-reads-red.txt](frontend-reads-red.txt) | `AdminReadPages.spec.ts`、`adminControls.test.ts`；阶段缺失、无虚构进度、旧数据、实例范围、审计前后值、trace 与搜索日志去 query |
| 浏览器发现的本地无密钥诊断 | [local-model-header-red.txt](local-model-header-red.txt) | 无密钥请求省略 Authorization；41 项模型/传输测试通过，真实本地 HTTP 模型测试通过，见 [model-probes-green.txt](model-probes-green.txt) |
| 无邮箱旧账号删除 | [frontend-legacy-confirm-red.txt](frontend-legacy-confirm-red.txt) | [frontend-legacy-confirm-green.txt](frontend-legacy-confirm-green.txt)；完整 UUID 确认，不接受显示名称，取消不删除 |

各独立新增行为先确认预期失败，再实现最小 GREEN。后续 RED 评审按用户“请继续，不再找我审批，一律确认”统一确认推进。补充既有行为回归测试不伪造 RED；新增生产行为仍保留实际 RED/GREEN 输出。

## 浏览器验收

隔离环境使用一次性 `knowra_verify` PostgreSQL（pgvector/pgvector:pg18）、本地 Vite/Uvicorn 和固定样例模型服务。全部模型请求到本机模拟服务，不使用真实付费供应商；数据库中的私有内容金丝雀未出现在任务/总览/审计页面。

- 六页在 320、768、1440px 均无整体横向溢出；窄屏导航 Esc 关闭及焦点归还通过。
- 搜索目标账号、额度确认、嵌套确认框 Tab/Shift+Tab、Esc 仅关闭顶层、会话取消不写入、撤销后旧会话真实返回 401。
- 删除需精确邮箱；密码表单关闭清空；模型保存→测试→编辑后过期→重测→显式默认切换通过。
- 分块失败详情准确显示实际尝试与“向量化尚未创建”；可按模型切换动作查审计并复制追踪标识。
- 数据库/pgvector 主动检查真实返回正常；文档模型禁用、外部模型未知均按真实状态展示。
- 成员与只读用户直接打开全部六页均不请求管理数据，直接接口返回 403；匿名访问跳转登录。

截图：[桌面总览](admin-overview-1440.png)、[320px 总览](admin-overview-320.png)、[320px 用户详情](admin-user-detail-320.png)、[320px 系统状态](admin-system-320.png)。其余六页三种屏宽截图见同目录。

## 迁移与回退

[真实迁移输出](data-postgres-roundtrip.txt)记录 `20261022_0001 → 20261022_0002 → 20261022_0001 → 20261022_0002`，仅在一次性验证库执行。核对账号、凭据、会话、额度、任务、资料链、非空向量和原默认绑定逐行不变，新增外键/索引与默认 revision 正确。

旧前端通过 `git archive b767b6bb5f309a60d55b6a1fdd8499fdf99b4633 front` 在临时目录构建，不切换当前工作树。浏览器在同一可信 Origin 提供旧 dist，API 继续访问新后端；确认实际旧入口回到 `/admin/users`，旧用户/模型列表和创建均成功，新增 revision 字段不破坏旧客户端。

回退前后逐项比较既有账号角色/状态/删除标记、额度、四用途绑定、所有原审计和诊断 ID、资料归属摘要及 `vector(2560)` 类型。旧前端两次创建各新增一条成功审计，既有记录均保留。该浏览器 fixture 没有已存向量，非空向量保留由上述迁移及后端隔离回归另行验证。

发布时备份数据库和原模型加密主密钥，先迁移及兼容后端，再发布前端。前端回退只替换构建，保留后台增量表、历史及已发生的账号/额度/模型操作；生产不执行会删除历史的 downgrade。

## 工作区与边界

[final-preservation-check.json](final-preservation-check.json)确认原 `add-admin-console` 三个未提交工件 SHA-256 完全保留，用户原有“修改我的密码”按钮样式保留，静态检查问题与原基线一致。原截图及 `.playwright-mcp/` 未清理。本地验收阶段未创建 Git 提交、未改生产业务库、未部署、未归档 OpenSpec；后续提交与推送按用户授权执行。

系统状态仅代表响应实例；本次未增加任务重试/取消、历史费用、集群监控或跨用户资料读取。长期审计/诊断保留策略仍按设计独立制定，首期不自动清理历史。

验收结束后，本次创建的 Vite、Uvicorn、模拟模型服务已停止，一次性容器 `knowra-admin-continue-verify` 已删除；证据文件与截图保留。
