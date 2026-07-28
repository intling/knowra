## Context

knowra 是 FastAPI（后端）+ Vue 3/Vite（前端）+ PostgreSQL/pgvector 的全栈应用。后端启动分两段：**bootstrap**（同步检查/下载 Docling 与 tokenizer 模型文件到磁盘）与 **runtime preload**（后台线程异步把模型加载进进程内存）。preload 处于 `loading` 期间，解析/分块请求会 fast-fail，此时容器虽已起、`/health` 返回 200、首页可打开，但核心链路不可用。向量化走云端 embedding API（OpenAI 兼容），依赖第三方可用性。

本变更不修改任何业务代码，仅新增 CI/CD、容器化与部署编排，复用上述既有运行时语义。所有决策来自与项目维护者的逐项确认。

## Goals / Non-Goals

**Goals**
- PR 上由有写权限成员评论 `/deploy` 即可把该 PR 分支全栈应用部署到**唯一共享预览槽位**并公网可访问
- 以「后端模型运行时就绪」为部署成功判据，保证回填的 URL 一打开即可走完整验证流程
- PR 关闭时自动清理槽位与预览数据库
- 公网暴露面最小化，满足网络安全约束

**Non-Goals**
- 不做「每 PR 一环境」的多环境并存（全局单槽位，last-write-wins）
- 不做本地 embedding（沿用云端 API；本地 embedding 为独立需求，另立变更）
- 不修改后端/前端业务代码，不新增数据库 migration
- 不做 HTTPS/域名（公网 IP + 高位端口 + Basic Auth）；不做「失败保留活容器」的交互式调试（留作以后 `/deploy keep`）

## Decisions

### 1. 单槽位，评论显式触发，last-write-wins
全局只有一个预览环境。只有 PR 评论 `/deploy` 才部署（不 PR 一开就自动抢占）。新的 `/deploy` 顶掉当前占用者。理由：同时可能有多个 PR 打开，自动抢占会让环境反复横跳，破坏验证质量；显式触发让「当前在验哪个 PR」始终明确。

### 2. self-hosted runner 就地执行，不走 SSH
在预览服务器上装一个（且仅一个）self-hosted runner（label `knowra-preview`，专用非 root 用户 `ghrunner` + docker 组），workflow `runs-on: [self-hosted, knowra-preview]` 就地 `docker compose`。理由：单台自有服务器 + 私有仓库 + 可信协作者场景下，无需开放 SSH、无需存部署私钥；只装一个 runner 从物理上保证单槽位串行（叠加 GitHub `concurrency` 双保险）。

### 3. 全栈预览：nginx + 后端 + 外部 PG
```
公网 :48080  nginx（Basic Auth）
                ├─ 托管前端 dist/（vue-tsc -b && vite build 产物）
                └─ /api 反代 → backend:8000（容器内网，端口不对公网映射）
backend 容器  ├─ bind mount /opt/knowra-preview/models → 容器内 storage/document-models/
              └─ 业务数据 storage/uploads|parsed|chunks 不持久化（随容器销毁）
外部 PG（另一台机，常驻，支持 pgvector）
```
前端生产必须靠 nginx 反代 `/api`（Vite proxy 仅 dev 生效），一并解决同源、避免 CORS。后端端口只在 compose 内网可达，杜绝绕过前端直连 API。

### 4. 数据库：固定库名，每次全新
库名固定 `knowra_preview`。每次 `/deploy`：`DROP DATABASE IF EXISTS knowra_preview` → `CREATE DATABASE` → `alembic upgrade head`。同名库天然自清理，外部 PG 上至多一个预览库，无孤儿库。顺带验证「该 PR 的迁移能否从零跑通」。业务数据（上传文件/解析产物/chunk）随容器每次重置。理由：预览就是拿 PR 分支重新验证，留旧数据反而干扰；固定库名比「按 PR 号命名」少一套孤儿库清理逻辑。

### 5. 模型持久化：bind mount 宿主机目录
`/opt/knowra-preview/models` bind mount 到容器内 `storage/document-models/`（Docling artifacts 与 tokenizer cache 同在其下，一个目录覆盖两类模型）。首次 `/deploy` 下载落盘，后续部署命中 bootstrap 的 `check` 直接跳过下载。设 `DOCUMENT_MODEL_HF_ENDPOINT=https://hf-mirror.com` 加速首次下载。理由：single-node 场景 bind mount 最透明可排障，且天然实现「模型留、业务清」；不烤进镜像（避免镜像臃肿与换版重构建）。

### 6. 成功判据：轮询 `/health` 直到模型运行时 ready
部署脚本轮询容器内 `GET /api/health`，直到 `document_models.status == "ready"` 才算成功、才回填 URL；带超时（首次下模型给足几分钟，后续复用卷后很快）。超时仍未 ready → 判失败。理由：模型两段式下，只等「容器 up / 200」会把 preload `loading` 的半可用环境当成功贴出，reviewer 一上传就 fast-fail，违背验证质量目标。

### 7. embedding：可验但不纳入成功判据
预览环境 `DOCUMENT_EMBEDDING_ENABLED=true`，key 从 secret 注入，reviewer 能真实走到向量化；但「部署成功」只由本地模型 ready 决定，不因外部 embedding API 抖动而判失败。理由：分块是本地能力（部署应保证），embedding 依赖第三方（尽力而为）；把外部 API 纳入判据会让部署成败受制于不可控服务并空烧 key 额度。

### 8. 访问与网络安全（公网硬约束）
- 入口：`http://<公网IP>:48080`，部署成功后 workflow 自动回填该 URL 到 PR 评论
- 访问控制：nginx **Basic Auth**，凭据存 GitHub secret，部署时由脚本用 `htpasswd` 等价方式生成 `.htpasswd`
- 后端端口**不对公网映射**；外部 PG 5432 **仅对预览服务器 IP 放行**
- key 只走 secret 注入容器 env：**不写镜像、不打日志、不回填评论**；评论只提示「凭据带外获取」
- self-hosted runner：仓库级注册、专用非 root 用户、专机专用、保持自动更新

### 9. 触发权限校验
`issue_comment` 触发时，workflow 先校验 `comment.author_association ∈ {OWNER, MEMBER, COLLABORATOR}`，否则忽略（可选回一句无权限）。理由：`/deploy` 会在服务器上执行 PR 代码并公网暴露，必须限权到有写权限的人。

### 10. 清理时机：PR 关闭且为槽位占用者
监听 `pull_request: [closed]`。宿主机状态文件 `/opt/knowra-preview/current-pr.txt` 记录当前占用槽位的 PR 号。close 时读取状态文件：仅当关闭的 PR == 占用者，才 `docker compose down` + `DROP DATABASE IF EXISTS knowra_preview` + 清空状态文件；否则 no-op（关的是没占槽位的 PR）。理由：谁占谁清，关闭即释放，语义清晰。

### 11. 并发：GitHub concurrency 串行化
两个触发入口（部署、清理）共用 `concurrency: { group: knowra-preview, cancel-in-progress: true }`。GitHub 服务端保证同组同时只跑一个 job，后触发顶掉正在跑的（与 last-write-wins 一致），避免边部署边清理、状态文件/端口/库互相打架。single-runner 是物理二道保险。

### 12. 反馈与失败处置
成功：回填预览 URL + 「凭据带外获取」提示。失败：回填失败阶段（建库/迁移/build/启动/就绪超时）+ Actions 日志链接。**失败即清理**，但拆除前强制抓日志：分阶段 job 日志 + `docker logs` + 最后一次 `/health` 输出，上传为 Actions artifact。理由：调试产物是日志而非活容器；半启动服务留在公网违背安全约束；「起来但坏了」的活容器调试留作以后按需的 `/deploy keep`（YAGNI，本次不做）。

## 单槽位状态机

```
状态文件 current-pr.txt：空 | <PR号>

/deploy PR#N（已过权限校验）:
  1. 抓取 PR#N head sha/branch
  2. docker compose down（清掉上一个占用者，无论是谁）
  3. 外部 PG: DROP+CREATE knowra_preview; alembic upgrade head
  4. 构建 backend/front 镜像；生成 nginx .htpasswd；compose up
  5. 轮询 /health 直到 document_models.status==ready（超时→失败）
  6. 成功: 写 current-pr.txt=N; 回填 URL
     失败: 抓日志→artifact; docker compose down; DROP DATABASE; 清空状态文件; 回填失败阶段+日志链接

pull_request closed PR#M:
  读 current-pr.txt
  若 == M: docker compose down; DROP DATABASE; 清空状态文件
  否则: no-op
```

## 脚本逻辑的可测试性（TDD 适配）

部署主体是 shell + docker + GitHub Actions，属于「配置/编排」，端到端只能在真实预览服务器与外部 PG 上验证，无法在 CI 单元测试中完整复现。为满足 TDD 要求，把**纯判定逻辑**从副作用中剥离到 `deploy/preview/scripts/lib.sh`，用不触网、不碰 docker 的可运行断言脚本 `lib_selfcheck.sh` 覆盖：
- PR 号从 `issue_comment` / `pull_request` 事件 payload 的解析
- 评论体是否为有效 `/deploy` 指令的判定（去空白、大小写、防 `/deployx` 误触）
- `author_association` 白名单判定
- 状态文件占用者比对（close 时是否应清理）
- `/health` 响应 JSON 中 `document_models.status == "ready"` 的判定与轮询超时计算

带真实副作用的部分（`docker compose`、`psql`、GitHub API 回帖）不写自动化测试，改为 `deploy/preview/README.md` 里的**手动 smoke 验收清单**逐条勾选。

## Risks / Trade-offs

- **self-hosted runner = 协作者可在服务器执行代码**：以「私有仓库 + 权限校验 + 专机专用 + 非 root 用户」缓解；接受 docker 组 ≈ root 的已知权衡（如需更强隔离可后续上 rootless Docker）。
- **公网 Basic Auth 明文传输**：无域名/证书下的取舍；凭据存 secret、可后续叠加 IP 白名单或 HTTPS。
- **首次 `/deploy` 慢**（下模型）：bind mount 卷 + HF 镜像缓解，仅首次；后续秒复用。
- **状态文件在宿主机、非事务**：single-runner + GitHub concurrency 串行化下不存在并发写；极端情况（close 事件永久丢失）用 README 手动清扫命令兜底，不引入常驻清理进程（YAGNI）。
- **端到端不可 CI 测**：接受；用剥离纯逻辑 + 手动 smoke 清单覆盖。

## Migration Plan

纯新增，无数据迁移、无 schema 变更。预览库 `knowra_preview` 每次部署重建，不影响任何生产/开发数据。回滚：删除 workflow 与 `deploy/preview/` 即可，无残留副作用（预览库可手动 `DROP`）。

## Open Questions

- 就绪轮询超时上限的具体秒数（首次下模型 vs 复用卷差异大）→ 实现时以变量给默认值并在 README 说明可调，不写死。
- 是否叠加 IP 白名单：reviewer 出口 IP 不稳定，暂不做，保留在 README 作为可选加固。
