## 说明：TDD 适配

本变更主体为 CI/CD 与容器/部署编排（配置类）。带真实副作用的部分（`docker compose`、`psql` 建删库、GitHub API 回帖、self-hosted runner 端到端）无法在 CI 单元测试中复现，按项目治理属于「纯配置/编排变更」，以 §8 手动 smoke 清单验收。

但部署脚本中的**纯判定逻辑**（指令解析、权限白名单、槽位比对、就绪判定与超时）可测且易错，MUST 按 Red-Green-Refactor 先写可运行断言测试。§2 为红测试阶段，输出后停在评审点，等待用户回复「继续」再进入 §3 绿测试实现。

## 1. 部署脚本纯逻辑骨架（仅签名/占位，供红测试导入）

- [ ] 1.1 新建 `deploy/preview/scripts/lib.sh`，定义纯函数占位（无副作用，仅回显/返回码）：`is_deploy_command <comment_body>`（判定是否有效 `/deploy`）、`is_authorized <author_association>`（写权限白名单）、`parse_pr_number <event_json> <event_name>`（从事件 payload 提取 PR 号）、`should_teardown_on_close <closed_pr> <state_file>`（close 时是否应清理）、`is_models_ready <health_json>`（判定 `document_models.status==ready`）。函数体先返回未实现状态，使断言失败
- [ ] 1.2 验证命令：`bash -n deploy/preview/scripts/lib.sh`（语法检查通过）

## 2. 部署脚本纯逻辑红测试（TDD：先红）

- [ ] 2.1 新建 `deploy/preview/scripts/lib_selfcheck.sh`，用 `assert` 风格（不触网、不碰 docker/psql）覆盖：
  - **正常路径**：`/deploy` → 有效；`OWNER`/`MEMBER`/`COLLABORATOR` → 授权；`issue_comment` 事件解析出正确 PR 号；`pull_request` 事件解析出正确 PR 号；状态文件占用者 == 关闭 PR → 应清理；`{"document_models":{"status":"ready"}}` → 就绪
  - **边界情况**：`  /deploy  `（含首尾空白）→ 有效；`/Deploy` 大小写策略按实现明确断言；空状态文件 → close 时不清理；`document_models.status` 为 `loading`/`unavailable`/`skipped` → 未就绪
  - **异常/边缘**：`/deployx`、`please /deploy later`、空评论 → 非部署指令；`author_association` 为 `NONE`/`CONTRIBUTOR`/空 → 未授权；事件 JSON 缺字段 → 解析安全失败（非崩溃）；状态文件占用者 != 关闭 PR → 不清理；`/health` 返回非法 JSON 或缺 `document_models` → 判为未就绪而非报错
  - 每个断言附清晰中文注释说明验证的逻辑与预期
- [ ] 2.2 确认 RED：运行 `bash deploy/preview/scripts/lib_selfcheck.sh`，确认因 `lib.sh` 函数未实现而断言失败
- [ ] 2.3 红测试评审点：停在此处，提示「红测试已生成，请评审。确认无误后回复『继续』，将进入绿测试阶段」，等待用户确认或修改意见后再进入 §3

## 3. 部署脚本纯逻辑绿测试实现（TDD：最小 GREEN）

- [ ] 3.1 在 `deploy/preview/scripts/lib.sh` 中实现 §1 各函数的最小逻辑，使 §2 全部断言通过
- [ ] 3.2 验证命令：`bash deploy/preview/scripts/lib_selfcheck.sh`（全部断言通过）+ `bash -n deploy/preview/scripts/lib.sh`

## 4. 容器化（后端 / 前端 Dockerfile）

- [ ] 4.1 新建 `backend/Dockerfile`：基于 Python 3.14、`uv sync` 安装依赖、以 uvicorn/gunicorn 运行 `app.main:app`；不将模型或 secret 打进镜像层
- [ ] 4.2 新建 `front/Dockerfile`：多阶段构建，`npm ci && npm run build`（`vue-tsc -b && vite build`）产出 `dist/`，产物阶段交由 nginx 托管
- [ ] 4.3 新建 `.dockerignore`：排除 `node_modules`、`.env`、`storage/`、`logs/`、`.git` 等，避免泄密与臃肿
- [ ] 4.4 验证命令：`docker build -f backend/Dockerfile backend` 与 `docker build -f front/Dockerfile front`（在预览服务器或本地 Docker 环境构建成功）

## 5. nginx 配置模板

- [ ] 5.1 新建 `deploy/preview/nginx.conf.template`：监听 48080、`auth_basic` + `.htpasswd`、`location /` 托管前端 `dist`、`location /api` 反代 `backend:8000`（保留必要 header）
- [ ] 5.2 验证命令：`nginx -t`（在 nginx 容器内以生成后的实际配置校验语法）

## 6. 预览容器编排

- [ ] 6.1 新建 `deploy/preview/docker-compose.preview.yml`：`nginx` 服务（映射公网 `48080`，挂载前端 `dist` 与 `.htpasswd`）+ `backend` 服务（`DOCUMENT_MODEL_*`/`DOCUMENT_EMBEDDING_*`/`DATABASE_URL` 经 env 注入，bind mount `/opt/knowra-preview/models` → 容器内 `storage/document-models/`，**不映射业务端口到宿主机**，业务数据目录不挂持久卷）
- [ ] 6.2 后端连接外部 Postgres 的 `knowra_preview`，`DOCUMENT_MODEL_HF_ENDPOINT` 默认 `https://hf-mirror.com`，`DOCUMENT_EMBEDDING_ENABLED=true`
- [ ] 6.3 验证命令：`docker compose -f deploy/preview/docker-compose.preview.yml config`（编排语法与变量插值校验通过）

## 7. 部署 / 清理脚本（副作用编排）

- [ ] 7.1 新建 `deploy/preview/scripts/deploy.sh`：`compose down`（清占用者）→ 外部 PG `DROP`+`CREATE knowra_preview`+`alembic upgrade head` → 生成 `.htpasswd` → `compose up -d` → 轮询 `/health` 至 `is_models_ready`（带超时）→ 成功写状态文件 `/opt/knowra-preview/current-pr.txt` / 失败抓日志(`docker logs` + `/health` + 分阶段输出)后 `down`+`DROP`+清状态文件。复用 §3 `lib.sh` 纯函数
- [ ] 7.2 新建 `deploy/preview/scripts/teardown.sh`：读状态文件，`should_teardown_on_close` 为真时 `down`+`DROP DATABASE`+清状态文件，否则 no-op
- [ ] 7.3 验证命令：`bash -n deploy/preview/scripts/deploy.sh deploy/preview/scripts/teardown.sh`（语法检查）；副作用行为由 §10 手动 smoke 验收

## 8. GitHub Actions workflow

- [ ] 8.1 新建 `.github/workflows/preview.yml`：触发 `issue_comment: [created]`（仅 PR 评论）与 `pull_request: [closed]`；`concurrency: { group: knowra-preview, cancel-in-progress: true }`；`runs-on: [self-hosted, knowra-preview]`
- [ ] 8.2 部署 job：`if` 守卫（评论以 `/deploy` 起 + `is_authorized`）→ checkout PR head → 调 `deploy.sh` → 成功用 GitHub API 回填含 URL 评论、失败回填阶段+日志链接并上传日志 artifact；secrets（PG 连接串、embedding key、Basic Auth）经 env 注入，不回显
- [ ] 8.3 清理 job：`pull_request: closed` → 调 `teardown.sh`
- [ ] 8.4 验证命令：workflow YAML 经 GitHub Actions 解析无 schema 错误（推送后 Actions 页面无解析报错）

## 9. 文档

- [ ] 9.1 新建 `deploy/preview/README.md`：self-hosted runner 安装与加固（专用 `ghrunner`、docker 组、label `knowra-preview`、仓库级注册、防火墙最小开放、x64）、所需 4 个 secrets 清单、外部 PG 前置要求（pgvector、建删库账号、IP 白名单）、单槽位语义与状态文件、手动清扫命令（孤儿库/残留容器兜底）、手动 smoke 验收清单
- [ ] 9.2 更新根 `README.md`：新增「PR 预览部署」章节，说明 `/deploy` 用法、权限要求、访问方式（`http://<IP>:48080`）与凭据带外获取
- [ ] 9.3 验证命令：人工检查文档与实际 workflow/compose/脚本变量名、端口、路径一致

## 10. 端到端手动 smoke 验收（真实预览服务器 + 外部 PG）

- [ ] 10.1 准备就绪：runner 上线（Idle）、`/opt/knowra-preview/models` 属主正确、外部 PG 可建删库且 pgvector 可用、4 个 secrets 已配置
- [ ] 10.2 有权限成员对一个 PR 评论 `/deploy` → Actions 触发 → 首次下模型 → `/health` 就绪 → PR 收到含 `http://<IP>:48080` 的评论
- [ ] 10.3 浏览器打开 URL → Basic Auth 通过 → 上传真实文档 → 解析 → 分块 → 向量化全链路可用
- [ ] 10.4 无权限用户评论 `/deploy` → 不触发部署
- [ ] 10.5 对另一 PR 评论 `/deploy` → 顶掉前一个、库重建、URL 指向新 PR
- [ ] 10.6 制造一次失败（如临时给错 PG 凭据）→ PR 收到失败阶段+日志链接评论 → 环境已清理、无残留容器/库、日志 artifact 可下载
- [ ] 10.7 关闭当前占用槽位的 PR → 容器与 `knowra_preview` 库被清理、状态文件清空
- [ ] 10.8 关闭一个未占用槽位的 PR → 环境不受影响
- [ ] 10.9 确认后端业务端口未对公网开放、成功/失败评论均不含任何密钥
