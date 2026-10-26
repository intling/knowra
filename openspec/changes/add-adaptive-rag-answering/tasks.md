# 自适应 RAG 回答策略实施任务

设计与契约见同目录 proposal.md、design.md 和 specs/。使用 Superpowers 的 TDD、writing-plans 与 verification-before-completion，按本文件在当前会话逐项推进。所有新测试使用中文注释说明业务意图；测试替身仅放在网络或 pgvector 边界。

## 1. 契约与 RED 评审

- [x] 1.1 完成四项能力规格和设计；运行 `openspec validate add-adaptive-rag-answering --strict`，修复契约矛盾和格式问题。
- [x] 1.2 在 `backend/tests/services/test_adaptive_rag_answering.py` 写普通问答、零召回、空库、资料澄清、提示词、历史和模型/Embedding 失败测试；运行该文件并确认新行为预期失败。
- [x] 1.3 在 `backend/tests/services/test_adaptive_rag_summary.py` 用真实 SQLite 资料覆盖总结范围、跨用户/删除隔离、最新分块版本、外置正文、预算与缓存；运行并确认预期失败。
- [x] 1.4 在 `backend/tests/api/test_adaptive_rag_api.py` 覆盖模式响应、范围参数校验、安全 404、未认证、模型未配置、成功通用问答计额与澄清释放；运行并区分新增失败与已有通过的保护用例。
- [x] 1.5 在 `front/src/components/layout/__tests__/ChatArea-adaptive.spec.ts` 和 `front/src/api/search-adaptive.test.ts` 覆盖通用回答、澄清、检索故障、总结覆盖、来源、旧记录及范围转发；运行并确认展示缺口导致失败。
- [x] 1.6 将 RED 实际命令、逐组结果与失败原因写入 `evidence/red-tests.md`；按 `openspec/config.yaml` 停在评审点，用户明确回复“继续”后才开始生产代码。

## 2. 回答契约、路由与生成 GREEN

- [x] 2.1 在 `backend/app/schemas/search.py` 增加有界 `document_ids` 和回答模式、检索状态、总结覆盖 schema；让范围格式用例通过，保留旧请求字段。
- [x] 2.2 新增 `backend/app/services/answer_policy.py`，实现闲聊/明确通用请求、资料依赖、文档概览路由与模式提示词；由 1.2 的公共服务行为验证，不能只测试规则常量。
- [x] 2.3 修改 `backend/app/services/search.py`，使普通问题空库/零召回仍生成，资料专属缺依据返回引导，Embedding 故障可区分降级；保持历史、模型错误、熔断与真实 token 行为，让 1.2 全绿。
- [x] 2.4 更新 `backend/README.md` 与 `backend/AGENTS.md` 的默认回答策略及契约；核对示例请求与 1.2、1.4 一致。

## 3. 文档总结、作用域和问答入口 GREEN

- [x] 3.1 新增 `backend/app/services/summary_context.py`：用户与删除过滤、最新成功分块、外置正文读取和 60,000 字符预算；总结提供真实来源及覆盖统计，让 1.3 的总结测试通过。
- [x] 3.2 在搜索编排与 SQL 中校验和应用文档范围，响应缓存纳入范围/策略版本；故障降级不缓存，让范围、隔离和缓存测试通过。
- [x] 3.3 修改 `backend/app/api/routes/search.py` 转发范围，取消空库对普通回答的 404，澄清释放额度，保留认证/模型配置/限额错误；让 1.4 全绿。
- [x] 3.4 更新受新契约影响的既有测试，保留权限、缓存和配额保护；运行 `uv run pytest tests/services/test_search_service.py tests/services/test_search_service_rewrite.py tests/api/test_search_api.py tests/api/test_search_route_rewrite.py tests/auth/test_search_isolation.py tests/auth/test_chat_quota_api.py tests/schemas/test_search_schema.py`。
- [x] 3.5 更新 `backend/README.md` 的范围、覆盖、错误和额度语义；无数据库变更，无需 Alembic migration。

## 4. 主对话展示 GREEN

- [x] 4.1 在 `front/src/api/search.ts` 声明可选新增字段并转发 `document_ids`，兼容旧缓存记录；让范围转发测试通过，运行 `npm run test -- src/api/search-adaptive.test.ts src/api/search.test.ts`。
- [x] 4.2 修改 ChatArea/AnswerPanel 按模式显示来源与归属，通用/澄清省略空来源和零引用，总结显示覆盖并省略语义分数；让 1.5 全绿并运行既有相关组件测试。
- [x] 4.3 更新欢迎页和输入区说明、`front/README.md`、`front/AGENTS.md` 与根目录 README，准确表达通用问答和资料增强；保留真实来源核对路径。

## 5. 综合验证

- [x] 5.1 运行后端 `uv run ruff check .`、`uv run ruff format --check .`、`uv run pytest`，记录实际结果并修复本次引入的失败。
- [x] 5.2 运行前端 `npm run lint`、`npm run test`、`npm run build`，记录实际结果并修复本次引入的失败。
- [x] 5.3 本地浏览器验证普通问答、无依据澄清、三文档总结、部分覆盖和来源展开，记录截图/检查结果及模型替身的适用范围。
- [x] 5.4 运行 OpenSpec 严格校验，检查 `git diff --check`、文件变更和规格覆盖，在 `evidence/verification.md` 报告验证与尚未部署的边界。

## Workflow follow-up

- 用户确认交付后可单独执行部署及线上 demo 冒烟验证，不把本地测试通过当作线上已生效。
- 完成实现与验收后再归档；本次不自动同步或归档其他未归档变更。
