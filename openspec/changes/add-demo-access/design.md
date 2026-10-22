# Design

## Context

动机见 proposal.md。已有用户体系支持数据库会话与用户资料隔离，但线上仍运行旧版与整站 Basic。额度必须归属用户，不能依赖浏览器、聊天线程或单进程内存。

## Goals / Non-Goals

**Goals:** 为共享演示身份持久化滚动小时额度，提供可直接分享的预填入口，维持原检索与来源返回协议。

**Non-Goals:** 不限制其他账号、不复制旧用户资料、不新增模型平台、付费配额或分布式队列，不自动登录。

## Decisions

1. `user_chat_limits(user_id PK/FK, hourly_limit CHECK > 0)` 配置账号额度；无配置则不限。`chat_usage(id UUID PK, user_id FK, created_at timestamptz)` 记录预留及成功调用，复合索引 `(user_id, created_at)`。Alembic 接在 `20261021_0001` 后，仅新增两表，不改 pgvector。
2. 在 search 的昂贵依赖之前做准入，验证 SearchRequest 后，通过 PostgreSQL 配置行 `FOR UPDATE` 锁完成清理过期记录、统计、插入和提交。禁止长时间持锁调用外部模型。以预留时间计算最近 60 分钟；HTTP 错误及 generation_error 降级释放预留，成功或缓存成功保留。超限返回 429 `chat_quota_exceeded`、中文 detail（含限额和稍后重试）及正整数 Retry-After。其他账号查询和问答保持原行为。
3. 预留必须在模型调用前提交，跨进程可见；失败清理先 rollback，再删除预留并 commit。请求取消在依赖 finally 中清理；正常关闭沿用既有 Uvicorn 在途请求排空，关闭期拒绝新任务。SIGKILL/主机崩溃不能保证清理，保守预留最多占用 60 分钟。无需新增后台资源或定时器；清理失败只记录固定结构化事件及预留 ID，不覆盖原异常，未释放记录自然过期。
4. `create-user --email ... --display-name ... --hourly-chat-limit 3 --password-stdin` 原子写入 member、Argon2 凭据和额度；在添加额度外键前 flush 父用户/凭据，保持单次 commit，失败时全部回滚。不允许密码命令行参数；重复邮箱、弱密码、非正数额度拒绝且不残留数据。保留 create-admin/reset-password 语义。
5. 链接采用 `/login#demo=<base64url(JSON({email,password}))>`。只接受 demo@deerfd.com、符合基本长度约束的字符串密码及有界有效载荷；拒绝任意账号、数组、异常 JSON 和重复 demo 字段。消费片段后以 replace 清除片段并保留合法站内 redirect。前端只在表单内存保存，不自动提交、不写入 storage、日志或 query；链接编码不是加密。页面提示共享演示账号最近 60 分钟最多成功问答 3 次。
6. 用户资料流程仍为上传 → 解析 → 分块/向量 → 问答准入 → 用户作用域检索 → 原模型生成带引用回答。未授权、CSRF 和参数错误仍使用现有契约且不扣次数。无向量资料返回现有 404；外部模型配置与超时/重试策略沿用已有实现，额度位于模型调用之前。

## Risks / Trade-offs

- 共享演示账号的额度由所有面试官共同使用 → 页面明确说明，429 含恢复等待时间。
- 进程被强制杀死时不能判定外部模型是否完成 → 保守占用直到窗口过期，避免额外费用和并发绕过。
- 公开链接包含可用演示凭据 → 仅预填指定 demo 身份，及时清除地址片段，不宣称编码保密；管理员凭据绝不进入链接。
- 线上切换 Basic 影响原探针 → 仅调整本站路由，检查匿名页面可打开、私有 API 401、Secure Cookie、监控预期及日志保护，不改其他站点。

## Migration Plan

先完成 RED 测试并遵守 openspec/config.yaml 的红测试评审门禁，再实现 GREEN。SQLite 验证服务、CLI/API 语义；真实 PostgreSQL 验证升级/降级和多连接并发。前端执行 lint、测试、build 及浏览器验证；后端执行相关 Ruff、全量 pytest 并如实说明既有问题。

上线遵循运维目录路由与原文：备份并验证源码、镜像/配置、数据库和匹配附件；隔离恢复验证增量迁移，停唯一写入者，使用 owner/migrator 执行 DDL 并保持 runtime 仅 DML。合并部署源已有的可选原生重排适配与原测试，保留候选数量、上下文排序和失败回退；不改变用户隔离。配置 HTTPS Secure Cookie、可信 Origin，构建不可变镜像及静态前端，切换后发布本站入口去除 Basic、保留 no-store 和安全日志。用真实公网浏览器验证片段填充、清除、主动登录及账号资料边界，额度测试不消耗正式 demo 使用记录。备份登记/恢复验证与 QMD 文档同步通过后交付链接。

回退前备份新增数据，仅回退本应用镜像、静态文件与本站入口；新增两表可保留以维持后续恢复，破坏性 downgrade 仅在确认无有效事件后执行。禁止覆盖或恢复整个共享数据库。
