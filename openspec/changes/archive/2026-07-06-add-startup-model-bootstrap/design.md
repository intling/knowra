## Context

knowra 现在的文档解析模型准备是懒加载的。PDF 解析进入 `DoclingParserAdapter._create_converter()` 后才创建 `PdfPipelineOptions`，只有当 `DOCUMENT_PARSE_DOCLING_CACHE_DIR` 目录非空时才把它传给 Docling；否则 Docling 会在 pipeline 初始化时访问 Hugging Face。受限网络下，这会让用户在上传后的解析作业中看到超时和泛化的 `parse_failed`。

分块也有类似隐患。`DoclingChunkerAdapter` 在执行分块时才通过 Transformers 加载 tokenizer，当前逻辑会先尝试本地缓存，再回退到网络下载。解析成功后自动分块，意味着一个文档可能先解析成功，再因为 tokenizer 下载失败而分块失败。

本变更把文档处理模型准备前移到应用启动后的 bootstrap 流程中：

```text
FastAPI lifespan startup
  -> DocumentModelBootstrapService
      -> 读取 DOCUMENT_MODEL_* 配置
      -> 设置 HF_ENDPOINT 等下载环境
      -> 检查 Docling artifacts
      -> 检查 tokenizer cache
      -> 按策略下载缺失模型
      -> 写入进程内 readiness
  -> yield app

解析/分块任务
  -> 读取 readiness
  -> ready: 使用准备好的本地目录
  -> not ready: 写入明确的 model_unavailable 错误
```

用户补充的关键约束是：`.env` 中必须使用全新的变量，不能复用或扩展任何既有变量。设计因此采用独立的 `DOCUMENT_MODEL_*` 命名空间；既有 `DOCUMENT_PARSE_*` 和 `DOCUMENT_CHUNK_*` 继续表达解析/分块业务行为，不作为 bootstrap 配置来源或 fallback。

## Goals / Non-Goals

**Goals:**

- 在应用启动后的生命周期中检查文档处理模型 readiness。
- 允许部署方通过新的 `.env` 变量指定 Docling artifacts 目录、tokenizer cache 目录和 Hugging Face 镜像地址。
- 支持 `check_only` 和 `download_missing` 两类 bootstrap 策略。
- 支持 `degraded` 和 `fail_fast` 两类启动失败策略。
- 在模型缺失时让解析/分块产生明确的 `model_unavailable` 错误，而不是等待第三方 SDK 网络超时。
- 保持变量命名空间隔离：bootstrap 只读取 `DOCUMENT_MODEL_*`，不复用、不扩展、不 fallback 到既有变量。
- 更新 README、后端 README 和 `.env.example`，说明离线和镜像部署方式。

**Non-Goals:**

- 不新增数据库表、迁移或持久化模型状态。
- 不实现前端模型管理页面、下载进度 UI 或用户可触发的模型下载 API。
- 不新增 `/api/health/document-models` 或其他独立模型健康检查 endpoint；模型 readiness 复用现有 `/api/health`。
- 不提供任意下载 URL。镜像只通过 Hugging Face Hub endpoint 配置表达。
- 不在本变更中实现生产级队列、后台下载任务、分布式锁、多进程文件锁或模型版本管理 UI。
- 不改变 embedding、语义检索、RAG 或引用生成范围。

## Decisions

### Decision 1: 使用独立的 `DOCUMENT_MODEL_*` 配置命名空间

新增配置建议如下：

```env
DOCUMENT_MODEL_BOOTSTRAP_ENABLED=true
DOCUMENT_MODEL_BOOTSTRAP_STRATEGY=download_missing
DOCUMENT_MODEL_BOOTSTRAP_FAILURE_POLICY=degraded
DOCUMENT_MODEL_DOCLING_ARTIFACT_DIR=storage/document-models/docling
DOCUMENT_MODEL_HF_ENDPOINT=
DOCUMENT_MODEL_DOCLING_REQUIRED_MODELS=layout,tableformer
DOCUMENT_MODEL_TOKENIZER_NAME=Qwen/Qwen2-7B
DOCUMENT_MODEL_TOKENIZER_CACHE_DIR=storage/document-models/tokenizers
```

这些变量只服务于启动模型准备。实现不得把 `DOCUMENT_PARSE_DOCLING_CACHE_DIR` 当作 Docling artifacts 的 fallback，也不得把 `DOCUMENT_CHUNK_TOKENIZER_MODEL` 或 `DOCUMENT_PARSE_DOCLING_CACHE_DIR` 当作 tokenizer bootstrap 的 fallback。

选择理由：

- 用户明确要求变量层面隔离和清晰。
- `DOCUMENT_PARSE_*` 关注解析功能开关、资源限制、OCR 和调度器；`DOCUMENT_CHUNK_*` 关注分块行为；`DOCUMENT_MODEL_*` 关注模型资产准备。
- 后续如果增加 embedding 模型、reranker 或 RAG 依赖，也可以继续放在模型准备命名空间下，而不污染解析/分块配置。

替代方案：

- 复用 `DOCUMENT_PARSE_DOCLING_CACHE_DIR`：配置少，但会混淆“解析运行缓存”和“启动模型资产目录”，不采用。
- 复用 `DOCUMENT_CHUNK_TOKENIZER_MODEL`：避免重复填写模型名，但违反变量隔离要求，不采用。

### Decision 2: 在 FastAPI lifespan 中执行 bootstrap

`create_app()` 已经使用 lifespan 统一处理启动阶段逻辑。新增 `DocumentModelBootstrapService`，在 lifespan 的 `yield` 前执行：

```text
bootstrap(settings)
  -> if disabled: state=skipped
  -> configure_hf_endpoint(settings.document_model_hf_endpoint)
  -> prepare_docling_models()
  -> prepare_tokenizer()
  -> app.state.document_model_readiness = result
```

`fail_fast` 策略下，如果 required 模型不可用，启动阶段抛出异常，中止应用启动。`degraded` 策略下，应用继续启动，但 readiness 标记为 `unavailable`，后续解析/分块任务使用明确错误失败。

选择理由：

- lifespan 是 FastAPI 官方启动边界，测试时可以通过 `create_app(settings)` 验证。
- readiness 保存在进程内即可满足首版需求，不需要数据库。
- 启动阶段的结构化日志可以让部署方在第一次请求前看到模型准备结果。

替代方案：

- 模块 import 时执行：难以控制日志和环境变量顺序，也不利于测试，不采用。
- 首次解析请求时执行：仍然把等待和失败留给用户操作路径，不采用。
- 独立 CLI 只做预下载：适合运维，但无法保证应用启动时检查结果，不作为唯一机制。

### Decision 3: Docling 只准备当前 PDF pipeline 需要的模型

当前 knowra PDF 解析关闭 OCR，但 `PdfPipelineOptions` 默认启用 layout 和 table structure。首版 required Docling 模型默认为：

- `layout`
- `tableformer`

实现可以调用 Docling 内部 downloader 或等价封装，效果必须等同于：

```bash
docling-tools models download -o "$DOCUMENT_MODEL_DOCLING_ARTIFACT_DIR" layout tableformer
```

不使用 Docling CLI 的默认模型集合，因为默认集合还包含 code/formula、picture classifier、rapidocr 等当前没有开启的能力。

选择理由：

- 降低首次启动下载体积和耗时。
- 与当前解析 pipeline 的真实依赖一致。
- 后续开启 OCR、图片分类或公式增强时，可以通过 `DOCUMENT_MODEL_DOCLING_REQUIRED_MODELS` 扩展。

替代方案：

- 下载 Docling 默认集合：省设计但慢，且会下载未启用模型，不采用。
- 只检查目录非空：会把 tokenizer cache 或半成品目录误判为可用，不采用。

### Decision 4: Hugging Face 镜像通过 endpoint 注入

`DOCUMENT_MODEL_HF_ENDPOINT` 用于设置 Hugging Face Hub 使用的 endpoint，例如 `https://hf-mirror.com`。该变量为空时使用 Hugging Face Hub 默认 endpoint。实现应在导入或调用 Hugging Face 下载逻辑前设置进程环境中的 `HF_ENDPOINT`。

选择理由：

- Docling 下载底层使用 `huggingface_hub.snapshot_download`，它支持 `HF_ENDPOINT`。
- 使用 endpoint 而不是任意 URL，避免把下载来源扩成不受约束的通用网络输入。
- 与国内镜像部署需求匹配。

替代方案：

- 在代码中硬编码镜像：不适合多部署环境，不采用。
- 给每个模型配置完整 URL：灵活但安全和维护成本高，不采用。

### Decision 5: readiness 进入解析和分块服务边界

解析任务开始执行实际 Docling 转换前必须检查 Docling readiness。若 readiness 不可用：

- `DocumentParseJob.status` 转为 `failed`
- `error_code` 为 `model_unavailable`
- `error_message` 包含缺失模型类型和准备建议

分块任务创建或执行前必须检查 tokenizer readiness。若不可用：

- `DocumentChunkJob.status` 转为 `failed`
- `error_code` 为 `model_unavailable`
- `error_message` 包含缺失 tokenizer 和准备建议

当重新分块请求指定与 `DOCUMENT_MODEL_TOKENIZER_NAME` 不同的 tokenizer 时，该 tokenizer 不属于启动准备保证范围。首版应优先拒绝并返回或记录 `model_unavailable`，除非后续单独设计多 tokenizer 准备清单。

选择理由：

- 错误从“第三方网络超时”变成项目内可诊断状态。
- 解析和分块作业表已经有错误码和错误信息字段，不需要新增数据模型。
- 用户上传资料后的反馈更快，前端可以继续使用现有失败展示。

替代方案：

- 在任务里继续尝试 SDK 自动下载：会回到当前问题，不采用。
- 自动把请求 tokenizer 临时下载：会引入用户路径上的网络等待，不采用。

### Decision 6: 可观测性使用结构化日志和可测试状态对象

bootstrap service 输出结构化日志，至少包含：

- `status`: `ready`、`unavailable`、`skipped`
- `strategy`
- `failure_policy`
- `docling_artifact_dir`
- `tokenizer_cache_dir`
- `missing_models`

进程内 readiness 结果使用项目内 dataclass 或 Pydantic model 表达，供测试、解析服务和分块服务读取。模型 readiness 对外只复用现有 `GET /api/health`，通过在现有响应中增加文档模型状态摘要表达，不新增 `/api/health/document-models`。

选择理由：

- 符合项目结构化日志约束。
- 避免为了首版 readiness 引入数据库、前端 UI 或新的 API 路由。
- 复用现有健康检查入口，部署侧只需要检查一个 health endpoint。
- 测试可以直接构造 readiness 对象覆盖 ready/unavailable 分支。

替代方案：

- 只写日志不保存状态：任务执行时无法快速判断，不采用。
- 写数据库：对首版启动级状态过重，不采用。
- 新增 `/api/health/document-models`：会扩大 API 表面，用户已明确首版不需要，不采用。

### Decision 7: 首版按 Docker 镜像交付和单进程启动假设处理

当前交付产物是 Docker 镜像，暂不要求多进程部署。首版不实现强文件锁或分布式锁；文档应说明推荐在镜像构建阶段或容器单进程启动阶段完成模型准备。

选择理由：

- 当前部署形态不需要处理多个 worker 同时下载同一批模型的复杂度。
- Docker 镜像可以把模型预热作为构建或启动流程的一部分，减少运行时网络不确定性。
- 锁机制可以在未来引入多进程/多副本部署时单独设计，避免首版过度设计。

替代方案：

- 首版实现跨进程文件锁：更稳健，但当前部署不需要，会增加测试和异常恢复复杂度，不采用。
- 依赖运行时多进程竞争自然收敛：行为不可控，不采用。

## Risks / Trade-offs

- 多 worker 同时启动下载可能重复写入模型目录 -> 当前不支持多进程部署，首版文档明确 Docker 镜像交付和单进程模型准备假设；未来多进程部署再补强文件锁。
- `download_missing` 会让应用启动变慢 -> 默认可按环境设为 `check_only`，并通过 `fail_fast` 或 `degraded` 控制启动结果。
- `DOCUMENT_MODEL_TOKENIZER_NAME` 与请求分块 tokenizer 不一致 -> 首版只保证配置声明的 tokenizer；请求不同 tokenizer 时返回明确不可用错误。
- Hugging Face endpoint 设置时机不当 -> bootstrap service 必须在调用 Docling/Hugging Face 下载逻辑前设置环境变量，并用测试覆盖。
- Docling 版本变更导致 artifacts 目录结构变化 -> readiness 检查应围绕 Docling 公开下载函数和当前 pipeline 所需模型，不只依赖目录非空。
- 降级启动可能让用户继续上传但解析失败 -> 作业错误必须明确为 `model_unavailable`，文档应建议生产使用 `fail_fast`。

## Migration Plan

1. 新增 OpenSpec 约束后，按 TDD 流程先补后端配置和 bootstrap service 测试。
2. 在 `Settings` 中增加 `DOCUMENT_MODEL_*` 配置，更新 `.env.example`，不删除既有变量。
3. 新增 `DocumentModelBootstrapService`、readiness 结果模型和下载/check 适配边界。
4. 在 FastAPI lifespan 中接入 bootstrap，并保持测试可注入。
5. 调整 Docling parser 和 chunker factory，使它们使用 bootstrap 准备的目录和 readiness，而不是旧缓存变量。
6. 调整解析/分块任务错误分支，输出 `model_unavailable`。
7. 更新现有 `/api/health` 响应以包含模型 readiness 摘要，不新增独立模型健康检查 endpoint。
8. 更新根 README、后端 README 和必要的 AGENTS/OpenSpec 说明，写明 Docker 镜像交付、单进程模型准备假设和暂不支持多进程下载锁。
9. 验证后端 ruff、format 和 pytest。

回滚时删除 bootstrap service、`DOCUMENT_MODEL_*` 配置、readiness 接入和文档说明，即可回到当前懒加载模型行为。新目录下已下载模型不参与数据库状态，可由部署方手动清理。

## Open Questions

- 无。已确认首版复用现有 `/api/health` 暴露模型 readiness，不新增 `/api/health/document-models`；已确认当前不要求多进程部署和强文件锁，最终交付产物为 Docker 镜像。
