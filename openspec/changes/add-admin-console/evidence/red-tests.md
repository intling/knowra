# 后台管理系统：首批红测试评审

## 当前状态

已完成提案、设计、三项增量规范与首批 100 项测试，仅新增工件和测试文件，未编写本变更的生产业务代码。仓库既有认证、RBAC、演示入口等未提交代码保持原状。

本阶段使用 `openspec-propose` 生成工件。全局 `openspec` 不在 PATH，使用环境已有 CLI：

```bash
node /root/.npm/_npx/abab5bd700860149/node_modules/@fission-ai/openspec/bin/openspec.js validate add-admin-console --strict
```

实际结果：`Change 'add-admin-console' is valid`。

## 设计摘要

- 后台入口 `/admin`，用户管理 `/admin/users`，模型配置 `/admin/models`。
- 用户新增、角色/启停、重置他人密码、软删除；沿用密码策略与资料私有边界，改密/删除撤销目标全部会话。
- 四种用途：chat、embedding、rerank、query_rewrite；每种用途可维护多个配置并选择一个默认，未绑定时回退对应环境配置。
- API Key 加密保存、只返回是否存在，编辑留空保留，清除需显式提交。
- 保存影响后续请求，正在执行的请求和任务使用已有配置快照；缓存及熔断按配置版本隔离。
- 不兼容的 Embedding 配置切换返回明确冲突，避免混用向量空间。

详细契约见 [设计](../design.md) 与 [规范](../specs/model-configuration/spec.md)。

## 执行与结果

后端执行于 `backend/`：

```bash
uv run pytest tests/admin_console tests/auth -q --tb=short \
  --junitxml=../openspec/changes/add-admin-console/evidence/validation/backend.xml
```

| 范围 | 通过 | 失败 | 跳过 |
| --- | ---: | ---: | ---: |
| 新增模型管理 API | 2 | 41 | 0 |
| 新增模型运行时解析 | 0 | 7 | 0 |
| 新增用户生命周期 API | 0 | 26 | 0 |
| 既有 tests/auth 回归 | 169 | 0 | 1 |
| 合计 | 171 | 74 | 1 |

实际退出码 1，10.21 秒。新增的两个通过用例证明既有 member/viewer 的权限集中不包含 `models:manage`；管理员尚缺该权限，按预期失败。既有跳过用例为需要 PostgreSQL 的并发配额测试。

前端执行于 `front/`：

```bash
npm run test -- \
  src/views/__tests__/AdminUsersLifecycle.spec.ts \
  src/views/__tests__/AdminConsole.spec.ts \
  src/views/__tests__/AdminUsersView.spec.ts \
  src/components/sidebar/__tests__/SidebarUser.spec.ts \
  src/router/__tests__/guards.spec.ts \
  src/api/adminUsers.test.ts \
  --reporter=default --reporter=junit \
  --outputFile.junit=../openspec/changes/add-admin-console/evidence/validation/frontend.xml
```

| 范围 | 通过 | 失败 |
| --- | ---: | ---: |
| 新增后台入口/模型配置交互 | 0 | 15 |
| 新增用户生命周期交互 | 0 | 9 |
| 既有用户管理/菜单/路由/API 回归 | 24 | 0 |
| 合计 | 24 | 24 |

实际退出码 1，3.92 秒。

静态检查均已实际执行并通过：

```bash
# backend/
uv run ruff check tests/admin_console
uv run ruff format --check tests/admin_console

# front/
npx eslint src/views/__tests__/AdminUsersLifecycle.spec.ts src/views/__tests__/AdminConsole.spec.ts
```

## RED 原因审查

- 用户 POST/DELETE/重置接口尚未提供，返回 405/404，测试断言明确列出操作条件、期望状态及实际响应。
- `/api/admin/models` 相关接口尚未提供，返回 404；不存在配置的用例还要求 `model_not_found`，现有通用 `Not Found` 不满足契约。
- 无绑定环境回退用例在测试函数执行时导入待实现的 `app.services.model_configuration`，因模块不存在失败；没有测试收集错误。
- 管理员权限缺 `models:manage`；前端缺模型路由、后台菜单文案以及建号/重置/删除控件。
- 所有失败均对应缺少目标行为，没有 fixture、依赖安装、语法或收集错误。

证据：[后端日志](validation/backend-red.txt)、[后端 JUnit](validation/backend.xml)、[前端日志](validation/frontend-red.txt)、[前端 JUnit](validation/frontend.xml)。

## 覆盖与后续批次

首批覆盖正常路径、输入边界、异常、身份权限、来源检查、秘密处理、用户资料归属、默认配置与索引保护。当前多数用例在缺少接口或页面处首先失败；后续密钥/事务等断言将随 GREEN 逐步执行，当前不能声称这些功能已实现或验证通过。

迁移与 PostgreSQL 行锁并发、模型适配器真实依赖接入、任务快照、缓存/熔断配置版本隔离、完整键盘可访问性与浏览器验证，按照 tasks.md 后续小批次继续先 RED 后 GREEN；不以 SQLite 测试替代 PostgreSQL 验证。本阶段不需要构建或启动尚未实现的页面，也未访问第三方模型或操作真实账号。

## 评审门禁

`openspec/config.yaml` 的 context 明确要求：

> 输出红测试代码后必须立刻停止生成，并明确提示用户：“红测试已生成，请评审。确认无误后，请回复‘继续’，我将进入绿测试阶段。”在用户明确回复“继续”或给出修改意见前，不得进入绿测试阶段。

因此停在首批测试评审点。任务 1.1–1.4 已完成，1.5 等待用户评审；其余生产代码任务均未勾选。

## 后续进展（2026-10-22）

用户已回复“继续”，上述 RED 评审点已通过。实现、回归、PostgreSQL 与浏览器验证已完成，最终结果见 [verification.md](verification.md)。前文保留为当时的红测试证据。
