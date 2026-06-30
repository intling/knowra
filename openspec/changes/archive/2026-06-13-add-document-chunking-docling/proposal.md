## Why

knowra 已经具备基于 Docling 的文档解析能力，但解析后的内容还不能被稳定切分为后续 embedding、语义检索、RAG 问答和引用定位可消费的知识单元。现在需要补上核心工作流中的“分块与索引”前半段，让解析结果转化为 token 长度可控、结构可追溯、可查询的文档 chunk。

## What Changes

- 新增文档分块能力，在文档解析后台任务成功后自动创建并执行分块作业。
- 调整解析结果的内部输出契约，使解析运行在持久化 Markdown、纯文本和 Docling JSON 的同时，保留只在当前后台任务内使用的 transient `DoclingDocument` 对象。
- 新增基于 Docling `HybridChunker` 的分块适配器，使用默认 `Qwen/Qwen2-7B` tokenizer 和可配置 `max_tokens`、`merge_peers` 等参数，从内存中的 `DoclingDocument` 直接生成结构化 chunk。
- 明确禁止从 `docling.json`、pickle 或其他已落地解析产物还原 `DoclingDocument` 后执行分块；首次分块只在解析运行仍持有内存对象时进行。
- 新增分块作业和分块结果持久化模型，保存作业状态、配置快照、分块器版本、错误信息、chunk 文本、contextualized 文本、token 计数、标题路径、页码、来源元数据和可选的来源 segment 索引。
- 新增分块结果的阈值混合存储策略：文本 `<= 2KB` 直接入库，`> 2KB` 写入文件存储并通过 `storage_key` 引用；`text`/`text_storage_key` 与 `contextualized_text`/`contextualized_text_storage_key` 各自互斥填充。
- 新增分块作业状态查询、分块结果分页查询、单个 chunk 详情查询和重新分块 API。
- 新增 `/rechunk` 行为：参数变更后重新读取原始上传文件，重新解析并重新分块，旧分块作业标记为 `superseded`，旧 chunk 结果保留但默认查询只返回最新活跃作业的结果。
- 明确分块不会修改、合并或覆盖既有 `document_segments`；只有在与同一次解析运行的 segment 映射可靠时才填充 `source_segment_indices`。
- 前端在解析完成后展示分块中、分块完成、分块失败和重新分块入口，并允许用户查看分块结果预览。
- 首版不实现 embedding、pgvector 索引、语义检索、RAG 问答、引用生成、多分块策略切换、独立 worker + 队列生产部署，或跨解析运行的 chunk 与旧 segment 自动强对齐。

## Capabilities

### New Capabilities

- `document-chunking`: 定义当前用户文档解析成功后的自动分块作业、Docling HybridChunker 适配、chunk 存储、查询 API、重新分块、权限边界、前端状态体验和首版非目标。

### Modified Capabilities

- `document-parsing`: 解析适配器和后台任务需要在内部结果中携带 transient `DoclingDocument`，并在解析成功后自动触发分块；该对象不得入库、写文件或通过 API 暴露。

## Impact

- 后端 API：新增分块相关路由，挂载在现有 `/api` 前缀下；新增重新分块 API 会触发重新读取原始上传文件、重新解析和重新分块；所有查询必须校验当前用户归属。
- 后端服务：新增 chunking adapter、chunking service、chunk artifact storage 和分块配置；调整解析任务成功路径，使其在同一后台任务内把内存中的 `DoclingDocument` 传给分块服务。
- 数据库：新增 `document_chunk_jobs`、`document_chunks` 相关 SQLModel 和 Alembic migration；解析既有表不应被分块过程修改。
- 后端依赖：确认当前 Docling 依赖可使用 `HybridChunker`；如使用 HuggingFace tokenizer，需要引入或确认 `transformers`/tokenizer 依赖和缓存目录配置。
- 后端配置：新增分块开关、默认 `max_tokens`、tokenizer 模型、`merge_peers`、`repeat_table_header`、文本入库阈值、分块产物目录和可能的 tokenizer 缓存配置。
- 前端：新增分块状态展示、结果预览和重新分块入口；避免把分块完成表述为已经完成语义检索或 RAG。
- 文档：同步更新 README、`.env.example`、后端/前端说明和验证命令，明确分块与 embedding、检索、RAG 的边界。
- 验收信号：上传并成功解析支持格式文件后，系统自动生成分块作业和 chunk 结果；chunk 可按当前用户分页查询；分块失败记录可诊断错误；重新分块会创建新作业并将旧作业标记为 `superseded`；测试能证明系统没有从旧 `docling.json` 还原 `DoclingDocument` 执行分块。
- 回滚说明：回滚时撤销前端分块入口、后端分块路由/服务、分块配置和 tokenizer 依赖，通过 Alembic downgrade 删除分块表；已写入的 chunk 文件产物按分块存储目录清理策略单独处理，原始上传文件和已有解析产物不受影响。
