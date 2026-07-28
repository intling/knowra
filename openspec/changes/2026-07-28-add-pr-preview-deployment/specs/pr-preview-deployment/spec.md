# PR Preview Deployment Spec

## Purpose

提供 PR 预览部署能力：由有仓库写权限的成员在 PR 上评论 `/deploy` 触发，通过预览服务器上的 self-hosted runner 就地构建并运行该 PR 分支的全栈应用到唯一共享预览槽位，以后端模型运行时就绪为成功判据，成功后回填公网预览 URL，失败时抓取分阶段日志后清理并反馈，PR 关闭时自动清理槽位与预览数据库。

## ADDED Requirements

### Requirement: 评论触发部署

系统 SHALL 在 PR 评论内容为 `/deploy` 指令且评论者具备仓库写权限时，将该 PR 分支的全栈应用部署到唯一共享预览槽位。

#### Scenario: 有权限成员触发部署成功
- **WHEN** 一个 `author_association` 为 `OWNER`/`MEMBER`/`COLLABORATOR` 的成员在 PR 上评论 `/deploy`
- **THEN** 系统在预览服务器上构建并运行该 PR 分支的 nginx + 后端容器，连接外部 Postgres 的全新 `knowra_preview` 库并执行 `alembic upgrade head`
- **AND** 待后端 `GET /api/health` 的 `document_models.status` 为 `ready` 后，在该 PR 回填包含公网预览 URL 的评论

#### Scenario: 无权限用户触发被忽略
- **WHEN** 一个 `author_association` 不在写权限白名单内的用户评论 `/deploy`
- **THEN** 系统不执行任何部署动作，不改变当前预览槽位状态

#### Scenario: 非部署指令不触发
- **WHEN** PR 评论内容不是有效 `/deploy` 指令（例如普通评论、`/deployx`、`please /deploy later`）
- **THEN** 系统不触发部署

### Requirement: 单槽位 last-write-wins

系统 SHALL 维护全局唯一的预览槽位。新的 `/deploy` SHALL 顶掉当前占用者，且同一时刻只有一个部署或清理流程在执行。

#### Scenario: 新部署顶掉当前占用者
- **WHEN** 槽位当前被 PR#A 占用，成员对 PR#B 评论 `/deploy`
- **THEN** 系统停止 PR#A 的容器、重建预览数据库、部署 PR#B，并将槽位占用者更新为 PR#B

#### Scenario: 并发触发被串行化
- **WHEN** 两个部署/清理事件几乎同时发生
- **THEN** 系统保证同组同一时刻仅执行一个流程，后触发者取消或顶掉正在执行者，不产生端口、数据库或状态文件的并发冲突

### Requirement: 模型运行时就绪作为成功判据

系统 SHALL 以后端 `GET /api/health` 返回的 `document_models.status == "ready"` 作为部署成功判据；在达到就绪前不得回填预览 URL。

#### Scenario: 就绪后才回填 URL
- **WHEN** 后端容器已启动但模型运行时仍处于 `loading`
- **THEN** 系统继续轮询而不回填 URL，直到状态变为 `ready` 才判定成功并回填

#### Scenario: 就绪超时判失败
- **WHEN** 在配置的超时时间内 `document_models.status` 始终未变为 `ready`
- **THEN** 系统判定部署失败，进入失败处置流程

### Requirement: 外部数据库固定库名全新重建

系统 SHALL 在每次部署时对外部 Postgres 使用固定库名 `knowra_preview`，先删后建再迁移，保证每次验证使用全新数据库。

#### Scenario: 每次部署重建预览库
- **WHEN** 触发一次部署
- **THEN** 系统对外部 Postgres 执行 `DROP DATABASE IF EXISTS knowra_preview`、`CREATE DATABASE knowra_preview`、`alembic upgrade head`，且不保留上一次部署的业务数据

### Requirement: 模型持久化与业务数据重置

系统 SHALL 将文档模型目录持久化到宿主机固定目录以跨部署复用，业务数据 SHALL 随容器销毁而重置。

#### Scenario: 模型跨部署复用
- **WHEN** 模型已在宿主机 `/opt/knowra-preview/models` 存在
- **THEN** 后续部署命中模型 bootstrap 检查并跳过重复下载

#### Scenario: 业务数据每次重置
- **WHEN** 触发一次新部署
- **THEN** 上一次部署的上传文件、解析产物与 chunk 产物不被保留

### Requirement: 公网访问安全

系统 SHALL 将预览应用以 Basic Auth 保护的高位端口对公网提供，后端业务端口不得对公网映射，敏感凭据不得泄露到镜像、日志或 PR 评论。

#### Scenario: 预览入口受 Basic Auth 保护
- **WHEN** 未提供有效凭据的请求访问公网预览端口
- **THEN** nginx 返回 401，不暴露应用内容

#### Scenario: 后端端口不对公网暴露
- **WHEN** 部署完成
- **THEN** 后端仅在容器内网可达，公网无法直连后端端口

#### Scenario: 凭据不进评论
- **WHEN** 系统回填成功评论
- **THEN** 评论包含预览 URL 但不包含 Basic Auth 密码或 embedding API key，仅提示凭据带外获取

### Requirement: 失败处置与日志抓取

系统 SHALL 在部署失败时先抓取诊断日志再清理环境，并向 PR 反馈失败阶段与日志链接。

#### Scenario: 失败先抓日志再清理
- **WHEN** 部署在任一阶段（建库/迁移/构建/启动/就绪超时）失败
- **THEN** 系统先抓取分阶段日志、`docker logs` 与最后一次 `/health` 输出并上传为构建产物，随后停止容器并删除预览数据库

#### Scenario: 失败反馈阶段与日志
- **WHEN** 部署失败处置完成
- **THEN** 系统在 PR 回填注明失败阶段与 Actions 日志链接的评论

### Requirement: PR 关闭时清理槽位

系统 SHALL 在 PR 关闭时，仅当该 PR 为当前槽位占用者才清理预览环境与数据库。

#### Scenario: 关闭占用槽位的 PR 触发清理
- **WHEN** 当前槽位占用者 PR 被关闭或合并
- **THEN** 系统停止容器、删除 `knowra_preview` 数据库并清空槽位占用记录

#### Scenario: 关闭未占用槽位的 PR 不动环境
- **WHEN** 一个未占用槽位的 PR 被关闭
- **THEN** 系统不改变当前预览环境与槽位占用记录
