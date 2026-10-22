# 演示访问与用户体系交付验证

2026-10-21，承接已完成的 add-user-auth-rbac。管理员身份为 active admin；demo@deerfd.com 为 active member，使用用户最后指定的密码，服务端配置最近 60 分钟最多 3 次成功问答。密码、哈希和完整凭据链接不写入本文件。

## 实现与测试

- RED 输出见 backend-red.log（32 failed、1 passed、1 skipped）和 frontend-red.log（19 failed、9 passed），用户回复“继续”后进入实现。
- 后端全量最终结果：1139 passed、5 skipped，见 backend-full-final.log。真实 PostgreSQL 并发与迁移另外实际执行；没有以 optional PG 跳过作为并发通过依据。
- 前端：51 文件、604 测试通过；lint、生产构建、受影响文件 Prettier 通过。
- 本次受影响后端文件 Ruff check/format 通过；全仓 Ruff 的 46 项既有错误和 7 个既有待格式化文件如实保留。
- 真实 PostgreSQL 恢复库验证额度迁移 upgrade → downgrade → upgrade，8 连接并发恰好 3 次准入、5 次拒绝，临时库及身份清理通过。新用户与额度外键排序问题按 RED/GREEN 修复并经 PostgreSQL CLI 复验。

## 线上验收

- 公网 https://knowra.deerfd.com，镜像 sha256:d8a4d325128cbd870fffb74aa6a2c3718b5923119714bbf077398ad8c7d54278，Alembic head 20261021_0002。保留生产原生 rerank 与显式 2560 维 embedding 配置。
- 桌面／手机浏览器验证实际分享链接：预填最后指定的凭据、清除片段、不自动提交；登录 Cookie 的 Secure/HttpOnly/SameSite/Path 正确，成员管理权限拒绝、注销撤销会话、清理地址重新加载不恢复密码。
- 临时独立用户真实公网注册、上传、解析、向量化及 DeepSeek 带来源问答；响应为 200/200/200/429，第四次换聊天线程仍带 Retry-After 拒绝。无资料错误不占额度；跨用户资料返回 404。正式 demo 不消耗测试次数，测试用户和四个业务文件已定点清理。
- 三条现行入口路径的 45 项检查通过；三路请求在本地安全日志与 Loki 各唯一命中，可信 IP、sensitive 路由及不记录凭据／canary 验证通过。仅移除本站 Basic，未恢复已退役入口。
- 生产 runtime 仅 DML，owner/migrator NOLOGIN；DDL、建角色、SET ROLE owner 与无关库连接拒绝复验通过。
- Knowra 单库云备份 20261021T072953Z 上传、全量回读、14 表隔离恢复通过。SQL 日备份不包含附件或主机秘密；匹配本地快照单独记录。

完整运维证据、备份与回退步骤位于 `/root/base-workspace/applications/knowra/checkpoints/demo-access-20261021T033431Z/`，最终 `checkpoint.json` 记录本地一致性快照、QMD 收尾和最终健康状态。唯一归属文档为 `/root/base-workspace/applications/knowra/README.md`。

演示账号共享资料及额度，目前没有预置文档，访客可通过上传流程体验。邮件验证／找回邮件、MFA、外部模型长期可用性及所有格式大文档不属于本次已验证范围。完整分享链接只在受保护秘密目录和向用户的交付回复中提供。

目录 render/validate、QMD refresh 和索引完整性均通过；MCP status 显示 0 原文漂移、0 待生成向量，代表性检索首位命中当前 Knowra 文档。
