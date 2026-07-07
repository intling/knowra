## 1. 契约与 RED 测试

- [x] 1.1 添加文档模型 runtime/preloader 单元测试，覆盖 bootstrap ready 后进入 `loading`、后台加载成功后进入 `ready`、加载失败后进入 `unavailable`、bootstrap `skipped/unavailable` 时不启动预加载。
- [x] 1.2 添加 FastAPI lifespan 测试，证明模型文件 bootstrap 后会启动非阻塞内存预加载，并把 runtime readiness 写入 app state。
- [x] 1.3 添加健康检查测试，证明 `/api/health` 返回 `loading` 组件摘要且不新增独立模型 endpoint。
- [x] 1.4 添加解析 API/dispatcher 测试，证明 Docling `loading` 时 PDF 解析请求或作业快速失败，纯文本解析不被阻塞，`ready` 时复用预加载 converter。
- [x] 1.5 添加分块 API/service/adapter 测试，证明 tokenizer `loading` 时 rechunk 或 chunk job 快速失败，`ready` 时复用预加载 tokenizer。
- [x] 1.6 运行新增 targeted tests 并确认它们因缺少 runtime/preload 行为按预期失败。

## 2. Runtime 与预加载实现

- [x] 2.1 新增进程内 `DocumentModelRuntime` 和组件状态对象，兼容既有 readiness 访问形态并保存预加载资源。
- [x] 2.2 实现默认预加载器：使用 Docling parser 配置创建 converter 并调用 `initialize_pipeline(InputFormat.PDF)`，使用本地缓存创建分块 tokenizer。
- [x] 2.3 在 FastAPI lifespan 中接入 runtime，bootstrap ready 后启动后台预加载且不阻塞 startup；shutdown 时释放后台任务引用。
- [x] 2.4 输出结构化日志，覆盖预加载开始、成功、失败和跳过状态。

## 3. 解析与分块接入

- [x] 3.1 调整解析创建接口和后台 dispatcher，使 Docling `loading/unavailable` 时快速返回或记录 `model_unavailable`，`skipped` 时保持旧行为。
- [x] 3.2 调整 `DoclingParserAdapter` 支持预加载 converter，并在 runtime ready 时复用该 converter。
- [x] 3.3 调整分块服务和 rechunk API，使 tokenizer `loading/unavailable` 时快速失败，`skipped` 时保持旧行为。
- [x] 3.4 调整 `DoclingChunkerAdapter` 支持预加载 tokenizer，并在 runtime ready 时复用该 tokenizer。

## 4. 文档与验证

- [x] 4.1 更新 `backend/.env.example`、根 README 和后端 README，说明模型文件 ready 后会异步预加载到内存、health loading 状态和 fail-fast 行为。
- [x] 4.2 运行 targeted backend tests 覆盖 runtime、lifespan、health、解析和分块。
- [x] 4.3 运行 `uv run ruff check .`、`uv run ruff format --check .` 和 `uv run pytest`。
- [x] 4.4 运行 `openspec status --change "async-preload-document-models"` 并确认 change apply-ready/任务完成状态。
