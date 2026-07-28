## Why

knowra 目前没有任何 CI/CD 或自动部署能力，PR 的验证只能靠 reviewer 在本地手动拉分支、起数据库、下模型、跑前后端。这个过程重、慢、易漏，尤其后端依赖 Docling 模型下载、pgvector 数据库和异步模型预热，本地复现成本高，导致 PR 很难被真实运行验证。

我们需要一条流水线：在 PR 上由有权限的成员显式触发后，自动把该 PR 分支的**全栈应用**部署到一台公网预览服务器的**唯一共享预览槽位**上，供人工点开真实界面走完整流程（上传 → 解析 → 分块 → 向量化）进行验证；PR 关闭后自动清理。目标是让「PR 是否真的能跑起来、能不能验证」变成一次评论就能得到的确定结果。

## What Changes

- 新增 GitHub Actions workflow `.github/workflows/preview.yml`，包含两个触发入口：
  - `issue_comment`：PR 评论 `/deploy` 时，校验评论者权限后把该 PR 部署到预览槽位
  - `pull_request: [closed]`：PR 关闭/合并时，若其为当前槽位占用者则清理环境
- 新增预览专用容器编排 `deploy/preview/docker-compose.preview.yml`：nginx（托管前端 `dist` + 反代 `/api` + Basic Auth）+ 后端容器（模型目录 bind mount、业务端口不对公网映射），后端连接**外部常驻 Postgres**
- 新增后端与前端的生产用 `Dockerfile`（当前仓库无任何 Dockerfile）
- 新增 nginx 配置模板 `deploy/preview/nginx.conf.template`（Basic Auth + 静态托管 + `/api` 反代）
- 新增部署/清理脚本 `deploy/preview/scripts/`：外部 PG 建删库 + `alembic upgrade head`、单槽位状态文件维护、`/health` 就绪轮询、失败日志抓取、容器与数据库清理
- 新增 `deploy/preview/README.md`：self-hosted runner 安装与加固、所需 GitHub secrets、单槽位语义、手动清扫命令
- 更新根 `README.md`：新增「PR 预览部署」章节，说明 `/deploy` 用法、访问方式与凭据获取途径
- **不涉及**：后端/前端业务代码变更（复用现有 `/health` 就绪语义）、数据库 schema 与 Alembic migration（仅在预览库执行既有 `upgrade head`）、本地 embedding 能力

## Capabilities

### New Capabilities
- `pr-preview-deployment`: PR 预览部署能力 —— 由有仓库写权限的成员在 PR 上评论 `/deploy` 触发，通过预览服务器上的 self-hosted runner 就地构建并运行该 PR 分支的全栈应用到唯一共享预览槽位；以后端模型运行时就绪（`/health` 的 `document_models.status == "ready"`）作为部署成功判据，成功后回填公网预览 URL 到 PR，失败时抓取分阶段日志后清理并反馈；PR 关闭时自动清理槽位与预览数据库

### Modified Capabilities
<!-- 无 -->

## Impact

- **新增（CI/CD）**：`.github/workflows/preview.yml`
- **新增（部署编排）**：`deploy/preview/docker-compose.preview.yml`、`deploy/preview/nginx.conf.template`、`deploy/preview/scripts/deploy.sh`、`deploy/preview/scripts/teardown.sh`、`deploy/preview/scripts/lib.sh`（PR 号解析、槽位占用判断、就绪轮询、日志抓取等纯逻辑）、`deploy/preview/scripts/lib_selfcheck.sh`（脚本逻辑的可运行断言检查）
- **新增（容器化）**：`backend/Dockerfile`、`front/Dockerfile`、`.dockerignore`
- **新增（文档）**：`deploy/preview/README.md`
- **修改（文档）**：根 `README.md`（新增 PR 预览部署章节）
- **依赖的现有基础设施**：后端 `GET /api/health` 的 `document_models` 就绪字段、`DOCUMENT_MODEL_*` 模型 bootstrap 与异步 preload、`DOCUMENT_EMBEDDING_*` 云端向量化、`alembic upgrade head`、`docker compose`
- **外部依赖（由运维手动准备，不在本变更代码内）**：预览服务器（公网 IP、x64、Docker、self-hosted runner，label `knowra-preview`）、外部常驻 Postgres（支持 pgvector、具备建删库权限的管理账号、5432 仅对预览服务器 IP 放行）、GitHub secrets（PG 管理连接串、embedding API key、Basic Auth 用户名/密码）
- **不涉及**：数据库 migration、后端/前端业务代码、环境变量新增（仅在部署时注入既有变量）、本地 embedding
