# 演示账号与预填链接：红测试评审

2026-10-21。采用用户最后指定的新密码；真实密码未写入源码、OpenSpec 或测试。测试使用独立假密码，并包含 `$`、`^`、`@` 等特殊字符，防止错误处理特殊符号。

## 需求与当前状态

- demo@deerfd.com 为普通成员；最近 60 分钟最多成功问答 3 次，所有设备和面试官共享额度，失败与生成降级不扣次数。
- 公网目标 https://knowra.deerfd.com/login；分享 URL 使用片段承载演示凭据，页面填表后替换地址去掉片段；用户主动点击登录。
- 本批仅新增 OpenSpec 和测试，未写生产实现、未创建 demo、未迁移或部署。尚无可交付的自动填充链接。
- 已有管理员和用户体系变更保持原状，未认领或复制任何旧用户资料。

## 可评审测试

- `backend/tests/auth/test_chat_quota.py`：滚动窗口精确边界、Retry-After 取整、三次限制、独立账号、无限制账号、释放幂等、连接重建、数据库约束与 PostgreSQL 并发。
- `backend/tests/auth/test_demo_cli.py`：特殊符号密码 stdin、member/额度初始化、无限制成员、邮箱重复、无效额度、弱密码、交互确认及原子性。
- `backend/tests/auth/test_chat_quota_api.py`：第四次拒绝且不构造适配器、重新登录/换聊天线程不重置、参数错误、依赖错误、模型错误/降级、无资料、认证及过期恢复。
- `backend/tests/auth/test_chat_quota_migration.py`：唯一迁移头、外键/正数/时区/索引约束与降级边界。
- `front/src/views/__tests__/DemoLogin.spec.ts`：填表但不登录、去片段保留 redirect、共享额度说明、主动提交、失败清空、不持久化、刷新不恢复及 12 类无效片段。

## 实际验证

后端执行：

```bash
cd backend
.venv/bin/pytest tests/auth/test_chat_quota.py tests/auth/test_demo_cli.py tests/auth/test_chat_quota_api.py tests/auth/test_chat_quota_migration.py -q
```

结果：32 failed、1 passed、1 skipped。失败原因分别为缺少 `app.models.chat_quota`（服务/API 尚未实现）、CLI 不支持 `create-user`、额度迁移文件不存在，均为预期 RED。匿名认证边界测试通过。PostgreSQL 多连接并发因未提供隔离恢复库连接而跳过，必须在 GREEN/发布验证时实际运行，当前不声称并发已验证。完整输出见 backend-red.log。

前端执行：

```bash
cd front
npm test -- --run src/views/__tests__/DemoLogin.spec.ts src/views/__tests__/LoginView.spec.ts
```

结果：19 failed、9 passed。新增预填测试 19 项预期失败，普通入口 1 项通过；既有 LoginView 8 项全部通过。失败原因是尚未填入邮箱/密码、展示额度说明或清除 URL 片段。完整输出见 frontend-red.log。

四个新增 Python 测试文件的 Ruff check/format 通过；新增前端测试文件 ESLint 与 Prettier check 通过。OpenSpec `validate add-demo-access --strict` 通过。

## 评审门禁与下一步

OpenSpec propose/apply 技能要求遵循项目 context/rules；openspec/config.yaml 明确要求“红测试输出后必须停止在评审点，等待用户回复‘继续’或提出修改意见；未获得确认前不得编写生产业务代码”。当前停在任务 1.4；任务进度为 3/18，不是功能完成。

确认后从这些 RED 测试进入最小 GREEN；随后完成真实 PostgreSQL 并发、迁移恢复、前端浏览器和线上部署验收。线上旧版仍有 Basic 门禁，发布时仅调整本站入口及相关探针，按运维路由完整读取规范并备份，不改其他站点。
