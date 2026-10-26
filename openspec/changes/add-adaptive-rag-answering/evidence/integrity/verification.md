# 回答完整性修正验收

日期：2026-10-26。用户反馈正文仅生成导语与首节标题，资料统计为 3/3 文档、46/46 片段。

## 结论与边界

代码确认：原适配器丢失 `finish_reason`，搜索服务只检查正文非空；输出长度结束会被当作完整成功并缓存、计额。
原默认输出预算 1024 tokens，整段生成硬限时 20 秒；前端 token 总数包含输入和输出，资料覆盖只表示输入已提供。
这些缺陷可复现截图所示表现，但没有采集该轮线上模型原始响应，不能断言截图的具体结束原因或实际输出配置。
前一轮使用模拟完整模型回答的测试没有覆盖此问题，本次补充真实 SDK 的 SSE 解析回归。

修正保留结束原因、最多两次长度续写、累计真实用量、默认 4096 输出预算和可配置 120 秒总截止时间。
仍未完成时保留正文与来源，返回 `answer_incomplete=true`，不缓存、不计成功额度，页面显示明确提示。
流在结束和取消时关闭。策略缓存版本升级为 `adaptive-v2`，防止命中旧半成品响应。
原有旧本地对话保持兼容，部署后需重新提问以获得新结果。

## TDD 与验证

沿用本变更已获得的“继续”授权，先更新契约并执行新增测试，再实现生产逻辑。

| 命令/检查 | 实际结果 |
| --- | --- |
| 后端完整性与总结/API RED（三个文件） | 18 failed、32 passed；预期缺少结束原因、续写、状态和预算配置 |
| 主对话 RED | 1 failed、12 passed；不完整告警缺失 |
| 同组后端 GREEN | 50 passed |
| 同组前端 GREEN | 13 passed |
| `uv run pytest -q --tb=short --show-capture=no` | 1538 passed、27 skipped，退出 0 |
| `npm run test` | 60 文件、666 passed，退出 0 |
| `npm run lint` | 退出 0 |
| `VITE_API_BASE_URL=/api npm run build` | 类型检查与 Vite 构建通过，退出 0 |
| 本次 12 个 Python 文件 Ruff/format | 全部通过 |
| 全量 `uv run ruff check .` | 39 条原有问题，9 个未修改文件，退出 1 |
| 全量 `uv run ruff format --check .` | 6 个原有文件需格式化，退出 1 |
| `openspec validate add-adaptive-rag-answering --strict` | 通过 |
| `git diff --check` | 通过 |

完整回归最初发现缓存版本隔离测试仍断言 `adaptive-v1`；同步两个版本断言后，隔离测试 9 项与完整后端回归通过。
静态检查与前次基线相同；本次修改文件没有新增问题。日志仅规整行尾空白，分别保存在本目录。

实际测试命令：

```bash
cd backend
uv run pytest -q tests/services/test_chat_completion_integrity.py tests/services/test_adaptive_rag_summary.py tests/api/test_adaptive_rag_api.py --tb=short --show-capture=no
uv run pytest -q --tb=short --show-capture=no
uv run ruff check .
uv run ruff format --check .
cd ../front
npm run test -- src/components/layout/__tests__/ChatArea-adaptive.spec.ts
npm run test
npm run lint
VITE_API_BASE_URL=/api npm run build
```

本机 OpenSpec 使用缓存中的 CLI 入口执行：

```bash
node /root/.npm/_npx/abab5bd700860149/node_modules/@fission-ai/openspec/bin/openspec.js validate add-adaptive-rag-answering --strict
```

## 浏览器

真实 Chromium 和 Vue 页面，在 API 边界提供确定性数据，不访问线上账号或模型。
9 项检查通过、0 个页面异常：覆盖正常/澄清/总结/部分输入/检索故障/生成失败/输出不完整及 390px 布局。
不完整场景保留正文、复制和三个来源，明确提示“回答尚未完成”，覆盖统计写作“已提供给模型”。
见 `browser-report.json`、`incomplete-desktop.png`、`mobile.png`。

```bash
# 先在 front 启动本地 Vite（端口 5177）
ADAPTIVE_PLAYWRIGHT_PATH=/path/to/playwright \
ADAPTIVE_BROWSER_BASE_URL=http://127.0.0.1:5177 \
ADAPTIVE_BROWSER_OUTPUT_DIR=/path/to/evidence/integrity \
node openspec/changes/add-adaptive-rag-answering/evidence/verify-browser.cjs
```

## 发布注意

未部署、未修改线上配置，未以真实模型验证最终回答质量。既有 `CHAT_MAX_TOKENS=1024` 显式环境值仍会生效，
部署时应核对并按供应商能力调为 4096–8192；`CHAT_GENERATION_TIMEOUT=120`，代理/进程超时须允许完整请求结束。
有界续写增加模型调用费用；供应商返回 `stop` 仅表示正常结束，不能保证内容语义上毫无遗漏。
