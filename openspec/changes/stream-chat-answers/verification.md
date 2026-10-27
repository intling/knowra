# 流式问答验证记录

## 交付状态

用户已确认 RED 评审并要求继续。模型增量、SSE、前端流式展示与生成反馈均已实现；主界面默认协商流式回答，旧 JSON 接口兼容。无新增应用依赖、运行配置、数据库表或迁移；未执行部署。

## 测试与检查

| 检查 | 实际结果 |
| --- | --- |
| 后端完整 pytest | **1554 通过，27 跳过**，耗时 82.48 秒 |
| 前端完整 Vitest | **693 通过**，64 个文件；使用 `--maxWorkers=2` |
| 前端 ESLint | 通过 |
| 前端 TypeScript 与 Vite 生产构建 | 通过 |
| 本次 4 个后端生产文件及新增后端测试的 Ruff check / format | 通过 |
| 后端全仓 Ruff check | 失败项均在本次未修改文件，包括旧迁移、uploads、postprocessor 和查询改写测试 |
| 后端全仓 Ruff format --check | 6 个未修改的既有文件待格式化，229 个文件已符合格式 |
| git diff --check | 通过 |

后端跳过项沿用各测试的外部环境条件，不将其计为已验证；真实 PostgreSQL 并发与真实供应商联网不由本次替身测试证明。前端第一次全仓执行时一个未修改的管理页测试因并发负载超过默认 5 秒而超时，限制为两个 worker 后完整通过；未改动该测试或放宽超时。

## RED → GREEN

初始 40 个新增测试实例中，32 个按预期失败，8 个兼容性守护通过。随后按实际链路补强为 43 个测试实例：

- 修正原始 ASGI 测试头字段为小写，显式确认先通过认证；分别验证带中间件和直接路由的取消。
- 将额度依赖恢复到旧 `scope="function"`，确认流期间预留提前释放导致断言失败，再改为请求级生命周期使其通过。
- 将响应恢复为原 `StreamingResponse`，确认直接路由在发送断开时未关闭上游，再恢复显式生成器清理使其通过。
- 浏览器检查发现来源元信息先到达会破坏贴底跟随，先新增失败测试，再共用元信息和正文的滚动更新逻辑；向上阅读仍不被打断。
- 恢复输入的测试检查 textarea 可用，并在填写下一问后确认发送可用，保留原有空输入禁止发送的规则。
- 中途断流虽保留正文，仍应计为模型调用失败；补强失败测试后修正熔断通知，避免部分正文把网络失败误记为成功。

覆盖增量在模型结束前交付、已交付正文不重复、长度续写及累计用量、中断/取消、缓存、真实 Cookie/资料范围/额度、UTF-8 拆包、CRLF、多行 data、错误帧、缺少终帧、Markdown 净化、生成反馈、对话与身份隔离、持久化和刷新恢复。

## 浏览器验证

使用独立 Chrome 上下文访问真实 Vite 前端；认证与资料使用既有虚构夹具，问答通过本地 HTTP 服务提供真正可控的 SSE 长连接。没有使用延迟播放完整 JSON 来模拟流式，也没有访问真实用户资料或模型供应商。

五组检查均通过，浏览器未处理异常为 0：

1. 首段在 HTTP 流结束前可见，来源、光标和生成状态可用，期间输入禁用。
2. 长回答新增正文不抢走回看前文的位置，外层应用壳不移动；正常结束恢复输入并显示最终实际夹具用量。
3. 390px 移动端无横向溢出；减少动态效果模式下光标和正文渐入的 animationName 为 none，静态状态与 Markdown 保留。
4. 强制断开 TCP 后保留正文与来源，提示未完成并恢复输入。
5. 通过 Vue 路由离开问答页后，HTTP 流被取消。

证据：[浏览器结果](evidence/browser/result.json)、[桌面生成中](evidence/browser/streaming-desktop.png)、[移动端减少动态效果](evidence/browser/streaming-mobile-reduced-motion.png)。

## 复现命令

在 `backend/` 中执行：

```bash
uv run pytest
uv run ruff check app/api/deps.py app/api/routes/search.py app/services/chat_adapter.py app/services/search.py tests/test_streaming_answers.py
uv run ruff format --check app/api/deps.py app/api/routes/search.py app/services/chat_adapter.py app/services/search.py tests/test_streaming_answers.py
```

在 `front/` 中执行：

```bash
npm run test -- --maxWorkers=2
npm run lint
npm run build
```

浏览器复现先启动前端，随后在根目录运行验收脚本。Playwright 作为独立测试工具提供，不加入应用依赖；可复用已有安装：

```bash
npm --prefix front run dev -- --host 127.0.0.1 --port 5173 --strictPort
# 在另一个终端执行，按本机安装设置测试工具路径。
KNOWRA_PLAYWRIGHT_MODULE=/absolute/path/to/playwright/index.mjs \
KNOWRA_CHROMIUM_PATH='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' \
node openspec/changes/stream-chat-answers/browser/accept-streaming.mjs
```

已有 Playwright 浏览器安装时可省略 `KNOWRA_CHROMIUM_PATH`。本次 MCP 预置浏览器缺失，使用本机已安装 Chrome 完成了同等浏览器检查；验收脚本退出时关闭浏览器及本地 SSE 测试服务。
