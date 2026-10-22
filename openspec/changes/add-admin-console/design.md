# 后台管理系统设计

## Context

动机见 `proposal.md`。工作区已有未提交但通过历史变更实现的认证、RBAC、会话、限额与用户管理基础，本变更增量扩展，不回退或覆盖已有工作。当前模型参数来自缓存的 `Settings`；搜索通过 FastAPI 依赖构造适配器，向量化还存在后台执行路径。现有 pgvector 列固定为 2560 维。

数据流：管理页面 → 统一 API client → Cookie/来源/权限依赖 → 账号或模型管理服务 → 数据库。资料接入 → 解析 → 分块 → 解析有效模型配置 → 向量化与索引；问题 → 解析有效模型配置 → 改写 → 向量检索 → 重排 → 生成 → 原有片段及引用展示。

## Goals / Non-Goals

目标：复用认证和现有适配器，以配置快照为边界，让后台保存真正影响新请求。模型管理是系统级配置；资料访问仍按用户隔离。明确错误契约，避免凭据回显、静默回退和不兼容索引切换。

非目标：不动态加载 Python 代码、不实现任意厂商协议、不新增后台队列、不代替索引迁移工具。首版只编辑接入基本参数；temperature、max_tokens 等生成调优沿用环境配置。

## Decisions

### 1. 用户管理增量扩展

复用 `user_admin`、密码规范化/哈希服务与 `revoke_user_sessions`。新增建号和重置 schema；建号事务写入账号与凭据并捕获唯一键冲突，返回 `email_conflict`；包括软删除用户在内邮箱均保持唯一占用。请求不接受客户端指定 UUID、权限集或归属。

重置他人密码先校验新密码，再原子更新凭据与撤销全部会话，保持禁用状态；自身改密继续走需要当前密码的账户设置。删除采用 `deleted_at` 加禁用和会话撤销，保留历史资料及所有权，不提供数据恢复或物理清除。用户删除、角色与状态修改使用共同事务 advisory lock，并按 UUID 顺序以 `FOR NO KEY UPDATE` 锁定有效管理员，在同一事务内重新校验操作者及目标状态，避免并发删除/降级突破管理员存续约束。用户主键不变，较弱的行锁允许向量任务 INSERT 的外键 `KEY SHARE`，防止其持有模型绑定锁时与管理操作交叉死锁。

沿用现有响应 `UserRead`；成功无响应体的重置与删除使用 204；错误沿用 `{code,detail}`，字段校验沿用不回显 input/ctx 的 422。新增接口均复用可信 Origin 校验。

### 2. 后台界面与权限

增加共享后台壳层（导航、返回知识库、标题区），复用现有 `AdminUsersView`，增加 `AdminModelsView`。`/admin` 重定向用户管理；账户菜单文案改为后台管理。页面在权限不足时不发管理 API 请求，服务端仍独立授权。

新增 `MODELS_MANAGE = "models:manage"`，仅 admin 角色包含，`UserRead.permissions` 返回新权限；同步前端权限类型和测试夹具。保留三类角色固定矩阵，不做任意权限编辑器。

表单可以采用页内展开编辑，避免无谓增加模态层。破坏性操作复用确认框；模态表单如使用则复用项目焦点工具。用请求状态阻止重复操作，列表、行及表单错误各自显示，关闭/成功清空秘密。分页删除最后一项后重新计算 offset。

### 3. 模型持久化和接口

`model_profiles`：UUID 主键，`name`（1–100）、`kind`（四个固定枚举）、`base_url`（最长 2048）、`model`（1–255）、`api_key_encrypted`（可空 Text）、`enabled`、`timeout_seconds`（1–120，默认 15）、`max_retries`（0–3，默认 1；rerank 固定 0）、`dimensions`（仅 embedding，固定 2560）、`api_format`（仅 rerank，`compatible` 或现有 `dashscope` 格式），`created_at/updated_at`。按用途及创建时间索引。

`model_bindings`：`kind` 主键与用途约束，`profile_id` 可空外键，`revision` 递增整数。迁移预建四行；激活/取消/默认配置修改锁定该用途绑定行，在单事务中检查兼容性并更新 revision。所有写入按绑定行、配置行的统一顺序加锁。外键限制删除已绑定配置；服务检查目标配置用途一致。响应 `is_default` 从绑定派生，避免多个布尔标记竞争。

| 接口 | 输入与结果 |
| --- | --- |
| `GET /api/admin/models` | `offset>=0,limit=1..100,kind?`；200 分页对象 |
| `POST /api/admin/models` | 名称、用途、地址、模型，可选密钥/启用/超时/重试/维度/重排协议；201 公开配置 |
| `PATCH /api/admin/models/{id}` | 局部更新，`kind` 不允许修改；200 公开配置 |
| `DELETE /api/admin/models/{id}` | 非默认配置；204 |
| `POST /api/admin/models/{id}/activate` | 设为该用途默认；200 公开配置 |
| `POST /api/admin/models/{id}/deactivate` | 仅当前默认可取消并恢复环境；200 公开配置，非默认返回 409 `model_not_active` |

地址仅允许 HTTP(S)，拒绝内嵌凭据、query、fragment；允许本机与私网部署地址。公开列表保留地址，因为它是管理员需要维护的信息。所有字符串去除首尾空白；无修改 PATCH 返回 422 `empty_update`。不在保存阶段访问外部地址。

### 4. 密钥存储

使用 `cryptography.fernet.Fernet`，主密钥来自 `MODEL_CONFIG_ENCRYPTION_KEY`，不放数据库，不自动生成临时主密钥。响应只暴露 `has_api_key`，不暴露密文。未提交或空 key 保持原密钥；显式 `clear_api_key=true` 清除，和非空 key 同传为 422。无鉴权本地配置允许无 key。

未设置主密钥时允许读取脱敏元数据及无密钥配置，但有秘密的创建、更新和运行时解密返回 503 `model_secret_unavailable`；旧默认配置不能解密时不回退环境。记录操作者、目标 ID、用途和事件，禁止记录原始 payload、明文 key、密文和主密钥。初始化/轮转及备份方法记入环境模板和后端 README；首版轮转需要运维离线重新加密或重新录入后再更换主密钥，禁止直接替换造成解密失败。

### 5. 运行时解析与生命周期

新增 `resolve_model_settings(session, base_settings)`，查询四种用途绑定并返回独立 `Settings` 副本，不修改 `get_settings()` 的 lru 缓存。新依赖仅用于模型使用路径，不替换认证、限额、健康检查或日志配置。映射前缀：`chat_*`、`document_embedding_*`、`rerank_*`、`query_rewrite_*`；启用后台默认 rerank/rewrite 时设置对应 enabled。rerank 现适配器没有重试参数，本期使用其已有单次调用语义，不展示可编辑重试；其余用途接入现有 max_retries。无绑定时完整沿用环境变量。

搜索在构造各适配器前只解析一次；配置版本参与搜索响应缓存、L1/L2 改写缓存、请求去重与熔断实例命名空间，保留 user_id，跨进程通过每次读取数据库绑定看到新版本。密钥不得进入命名空间。未配置后台时保持现有行为和缓存稳定。

自动向量化与重新向量化均在任务调度处捕获不可变配置，后台通过独立 session 执行；不把 request session 交给任务，不把明文 key 写入 job 的 JSON snapshot。后台已指定 Embedding 时，重新向量化请求若覆盖不同模型或维度，返回 409 `embedding_configuration_managed`；未指定后台默认时保留原环境路径的参数兼容性。后台 Embedding 绑定会启用自动向量化，解析和分块开关仍遵循环境设置。请求结束释放 session 和短生命周期外部客户端；共享改写器只共享缓存与状态，LLM 客户端每次调用结束立即关闭，因此切换时无需保留长连接。在途任务使用旧配置并遵循既有 queued/running shutdown 标记和停止接收新任务规则；新服务不持有线程、文件句柄或长连接。cleanup 异常通过固定事件加字段记录且不阻塞退出。SIGKILL 与宿主机崩溃沿用现有不可捕获边界，不声称一定完成清理。

### 6. 向量空间一致性

新建配置本身不影响索引；激活 embedding、修改当前默认 embedding 的地址/模型/维度、取消默认恢复环境时，检查是否有未删除用户的有效 succeeded 向量作业。存在时只允许有效 `(base_url,model,dimensions)` 不变，否则 409 `embedding_index_conflict`。同维度不代表同空间，不能仅校验维数。所有用途写入绑定锁与向量作业入队捕获配置的协调须覆盖切换与入队并发窗口；存在 queued/running embedding 任务也视为受保护，避免未完成向量写入旧空间。密钥、名称和超时修改不影响空间身份。

### 7. 测试与交付

先编写 API、运行时解析与前端交互测试，运行确认预期 RED，然后遵守 `openspec/config.yaml` 的显式红测试评审门禁。每个测试带中文意图说明，失败包含具体业务条件与响应上下文。红测试证据及既有回归基线放入 `evidence/`，不修改既有变更工件。

GREEN 后运行后端 `uv run ruff check .`、`uv run ruff format --check .`、`uv run pytest` 和前端 `npm run lint`、`npm run test`、`npm run build`。PostgreSQL 实测 upgrade/downgrade/upgrade 验证表、绑定种子和数据保留，并用真实数据库检验默认切换与管理员存续并发。浏览器验证管理员入口、用户操作、四种模型配置、非管理员拒绝、错误态和 320px 布局；所有第三方模型调用均 mock，不动生产数据。

## Risks / Trade-offs

- 配置按请求查库增加固定查询成本 → 一次查询解析全部绑定，首版优先保证跨进程生效，不引入失效复杂的本地配置缓存。
- 加密主密钥丢失导致已存密钥不可恢复 → 主密钥独立备份，缺失明确报错，允许管理员重新录入。
- 新旧模型同名但服务实现变化无法自动识别 → 地址和模型标识共同约束；真实模型升级需独立索引迁移流程。
- SQLite 不能证明 PostgreSQL 行锁语义 → 单元/API 测试用 SQLite，正式完成前必须补 PostgreSQL 并发与迁移验证。
- 工作区已有大量未提交变更 → 新文件和最小增量修改，不 reset、不提交用户已有代码，不操作真实账号。

## Migration Plan

1. 备份数据库和环境配置，生成并独立保存加密主密钥；新增迁移继承当前 chat-quota revision。
2. 执行迁移创建模型配置表及四行空绑定，已有账号、会话、配额、索引不变。
3. 发布代码，在未选后台默认时验证环境配置兼容；管理员逐用途录入并确认激活。
4. 回滚前清空绑定或取消默认恢复环境配置，再回退代码；必要时仅 downgrade 本次模型表迁移，保持既有所有权数据。
