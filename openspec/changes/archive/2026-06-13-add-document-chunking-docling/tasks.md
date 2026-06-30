## 1. 后端契约、Spike 与红测试

- [x] 1.1 用最小 fixture 验证当前依赖中的 Docling `HybridChunker` 导入路径、`contextualize()` 行为、`Qwen/Qwen2-7B` tokenizer 加载方式和缓存目录要求，并记录是否需要更新依赖。
- [x] 1.2 准备最小分块测试 fixture，覆盖 Markdown/TXT 兜底样例和至少一个由 Docling 解析产生 `DoclingDocument` 的小型样例，避免 OCR 或大文件进入默认测试集。
- [x] 1.3 为分块配置编写失败测试，覆盖分块启用开关、默认 `max_tokens=512`、默认 tokenizer 模型、`merge_peers`、`repeat_table_header`、文本入库阈值 `2048` 字节和分块产物目录。
- [x] 1.4 为 `DocumentChunkJob`、`DocumentChunk` 模型和 Alembic migration 编写失败测试，覆盖字段、外键、状态枚举、索引、downgrade 和 `superseded` 状态。
- [x] 1.5 为解析内部结果携带 transient `DoclingDocument` 编写失败测试，覆盖 Docling 解析成功后返回内存对象、对象不进入数据库/文件/API 响应、TXT 或不支持原生对象时的清晰缺失语义。
- [x] 1.6 为 Docling 分块适配器编写失败测试，覆盖 HybridChunker 调用、默认 tokenizer 配置、chunk 顺序、原始文本、contextualized 文本、token_count、heading_path、page_numbers、metadata_json 和异常转换。
- [x] 1.7 为 chunk 文本阈值混合存储编写失败测试，覆盖短 `text`/`contextualized_text` 直接入库、长文本写入文件存储、对应字段互斥和 storage key 路径稳定。
- [x] 1.8 为 `DocumentChunkingService` 编写失败测试，覆盖创建作业、状态流转、配置快照、保存 chunk、缺少 transient `DoclingDocument` 时失败、分块失败不回滚解析结果，以及不修改 `document_segments`。
- [x] 1.9 为解析成功路径自动分块编写失败测试，覆盖 `run_parse_job` 保存解析结果后把同一个 transient `DoclingDocument` 传给分块服务、分块禁用时不创建作业、分块失败时解析作业仍为 `succeeded`。
- [x] 1.10 为重新分块服务编写失败测试，覆盖归属校验、原始上传文件不可用、运行中作业返回 `409`、重新读取原始上传文件并重新解析、不读取旧 `docling.json`/pickle、重分块运行中旧作业仍为活跃结果、重分块失败不取代旧结果、新作业成功后才将旧作业标记为 `superseded` 并切换活跃结果。
- [x] 1.11 为分块 API 编写失败测试，覆盖 `GET /api/document-chunk-jobs/{job_id}`、`GET /api/parsed-documents/{parsed_document_id}/chunks`、`GET /api/document-chunks/{chunk_id}`、`POST /api/parsed-documents/{parsed_document_id}/rechunk` 的成功、分页、权限拒绝、空状态、409 和错误响应。
- [x] 1.12 运行新增后端测试并确认因分块能力尚未实现而 RED，然后停止在红测试评审点，提示用户评审并回复“继续”后再进入实现阶段。

## 2. 后端实现

- [x] 2.1 根据 spike 结果更新后端依赖和锁文件，确保 `HybridChunker`、HuggingFace tokenizer 和缓存目录在项目环境中可用。
- [x] 2.2 在 `backend/app/core/config.py` 和 `backend/.env.example` 中增加分块配置，包含启用开关、tokenizer 模型、max_tokens、merge_peers、repeat_table_header、文本入库阈值和分块产物目录。
- [x] 2.3 新增 `backend/app/models/document_chunking.py` 中的 `DocumentChunkJob`、`DocumentChunk` 模型，并确保模型被 Alembic metadata 发现。
- [x] 2.4 新增 Alembic migration 创建 `document_chunk_jobs` 和 `document_chunks` 表、外键、索引和 downgrade。
- [x] 2.5 新增分块 API schema，统一作业状态、配置快照、chunk 列表分页、chunk 详情、重新分块请求和错误响应结构。
- [x] 2.6 调整解析适配器内部输出契约，使 Docling 解析结果携带 transient `DoclingDocument`，并确保可持久化 payload 与 API 响应不包含该对象。
- [x] 2.7 实现 `DoclingChunkerAdapter`，封装 HybridChunker、tokenizer 初始化、`contextualize()`、元数据规范化和异常转换。
- [x] 2.8 实现 `ChunkArtifactStorage`，按阈值保存 chunk 原始文本和 contextualized 文本，并返回稳定 storage key。
- [x] 2.9 实现 `DocumentChunkingService`，编排分块作业创建、状态更新、配置快照、chunk 保存、权限过滤和失败记录。
- [x] 2.10 在 `run_parse_job` 成功路径末尾接入自动分块，保证使用同一任务内的 transient `DoclingDocument`，且分块失败不回滚解析结果。
- [x] 2.11 实现重新分块流程，校验解析结果归属和原始文件可用性，重新读取原始上传文件并重新解析，不读取旧 `docling.json`，在新作业运行中和失败时保持旧活跃结果不变，仅在新作业成功持久化完整 chunk 集合后将旧活跃作业标记为 `superseded` 并切换默认查询结果。
- [x] 2.12 新增分块 API 路由并注册到后端 API router，所有业务接口继续挂载在 `/api` 前缀下。
- [x] 2.13 运行后端相关测试，确认模型、migration、配置、适配器、服务、解析接入和 API 达到 GREEN。

## 3. 前端契约与红测试

- [x] 3.1 为前端 document chunking API client 编写失败测试，覆盖查询分块作业、分页查询 chunks、读取 chunk 详情和触发重新分块。
- [x] 3.2 为上传/解析后的分块状态体验编写失败测试，覆盖分块中、分块完成、分块失败、重新分块运行中旧预览仍可见、重新分块失败保留旧预览，以及权限/网络错误反馈。
- [x] 3.3 为 chunk 预览体验编写失败测试，覆盖按顺序展示 chunk 文本、标题路径、页码、token 计数和空状态。
- [x] 3.4 为“分块完成不等于已检索/RAG 可用”编写失败测试，确认 UI 文案不承诺 embedding、语义检索或问答能力。
- [x] 3.5 运行新增前端测试并确认因分块前端能力尚未实现而 RED，然后停止在红测试评审点，提示用户评审并回复“继续”后再进入实现阶段。

## 4. 前端实现

- [x] 4.1 新增 `front/src/api/documentChunking.ts` 及类型定义，复用现有 API client 和 `VITE_API_BASE_URL` 约定。
- [x] 4.2 更新上传/解析后的页面状态模型，接入分块作业状态展示和错误反馈。
- [x] 4.3 新增 chunk 预览 UI，展示 chunk 顺序、文本、标题路径、页码和 token 计数，并保持界面安静、可扫描。
- [x] 4.4 新增重新分块交互，支持配置可暴露的参数、运行中禁用重复触发，并展示 409 或原始文件不可用等错误。
- [x] 4.5 更新 UI 文案，明确当前阶段是“分块完成/可预览”，不承诺已完成向量索引、语义检索或 RAG 问答。
- [x] 4.6 运行前端相关测试，确认 API 封装、状态体验、chunk 预览和重新分块交互达到 GREEN。

## 5. 文档与配置同步

- [x] 5.1 更新根 README 和后端 README，说明分块 API、分块配置、HybridChunker/tokenizer 依赖、产物目录、内存直传约束和 `/rechunk` 重新解析行为。
- [x] 5.2 更新 `.env.example`，补充分块开关、tokenizer 模型、max_tokens、merge_peers、repeat_table_header、文本入库阈值、分块产物目录和缓存说明。
- [x] 5.3 更新前端 README，说明解析完成后的分块状态、chunk 预览和重新分块体验。
- [x] 5.4 在文档中明确首版不实现 embedding、pgvector 索引、语义检索、RAG 问答或引用生成。
- [x] 5.5 如果实现过程中发现 Docling `HybridChunker`、tokenizer、重新分块时序或解析内部契约与设计不匹配，先更新本 OpenSpec 变更再继续实现。

## 6. 集成验证与收尾

- [x] 6.1 运行 `uv run ruff check .` 验证后端静态检查。
- [x] 6.2 运行 `uv run ruff format --check .` 验证后端格式。
- [x] 6.3 运行 `uv run pytest` 验证后端测试。
- [x] 6.4 运行 Alembic upgrade/downgrade 验证分块 migration 可正向和反向执行。
  - 2026-06-12：在线执行受当前数据库状态阻塞；当前 `.env` 指向的数据库 Alembic 版本为 `20260605_0001`，但 `document_chunks` 表已存在，`uv run alembic upgrade head` 在 `20260612_0001` 报 `DuplicateTable`。本机默认 `knowra/knowra` PostgreSQL 凭据不可用，Docker CLI 不存在，未对远端库做清理或 downgrade。已补充生成 `uv run alembic upgrade head --sql` 和 `uv run alembic downgrade 20260612_0001:20260605_0001 --sql` 作为非破坏性校验。
  - 2026-06-13：结合当前项目数据库状态重新验证；当前 `.env` 指向库已在 `20260612_0001`，存在新版 `document_chunk_jobs`/`document_chunks`，并保留旧原型表 `legacy_document_chunks_20260612_0001`。为避免破坏已有数据，使用同一 PostgreSQL 实例临时库 `knowra_migration_verify_*` 实际执行 `upgrade 20260605_0001`、`upgrade 20260612_0001`、`downgrade 20260605_0001`、`upgrade head`；已验证分块表字段、索引、正向创建、反向删除和重升 head，临时库已清理。
- [x] 6.5 运行 `npm run lint` 验证前端静态检查。
- [x] 6.6 运行 `npm run test` 验证前端测试。
- [x] 6.7 运行 `npm run build` 验证前端构建。
- [x] 6.8 启动本地前后端并执行 smoke check：上传样例文件、自动解析、自动分块、查询 chunk 列表、查看 chunk 详情、触发重新分块，并确认没有读取旧 `docling.json` 作为分块输入。
  - 2026-06-12：受 6.4 数据库状态阻塞，未启动本地前后端执行端到端 smoke check。
  - 2026-06-13：使用同一 PostgreSQL 实例临时库 `knowra_smoke_*` 启动后端 `uvicorn` 和前端 Vite dev server；通过 HTTP 完成健康检查、样例 DOCX 上传、自动解析、自动分块、chunk 列表查询、chunk 详情查询。触发 `/rechunk` 前主动移除本次解析落地的 `docling.json`，`POST /api/parsed-documents/{id}/rechunk` 仍返回 `202` 且旧活跃 chunk 预览保持可查，确认重分块触发不依赖旧 `docling.json`；临时库已清理。
