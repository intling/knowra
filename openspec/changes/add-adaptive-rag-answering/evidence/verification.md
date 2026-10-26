# 自适应 RAG 实现验收记录

日期：2026-10-26。变更：`add-adaptive-rag-answering`。用户回复“继续”后进入 GREEN。

## 交付行为

- 问候和明确通用请求跳过改写与 Embedding，其他普通问题在空库/零召回时仍调用模型回答。
- 资料增强提示词优先真实来源，允许标明归属的通用解释；私有事实没有依据时澄清。
- 文档总结直接读取当前用户可见资料的最新成功分块，支持未向量化和外置正文。
  最多自动处理 20 份，正文预算 60,000 字符，覆盖不完整时同时向模型与界面披露。
- `document_ids` 限定范围并在缓存命中前校验；检索、计数、总结及缓存遵守用户与软删除边界。
- 总结缓存包含文档集合及最新成功分块版本，删除、未向量化资料新增和重分块会失效。
  检索不可用及生成失败不缓存。成功通用回答同样计额，澄清释放预留。
- 主对话按模式展示正文、来源与覆盖；通用/澄清省略空来源与零引用，总结不展示语义分数或检索排名。
  旧本地记录保持兼容，模型失败不会被标为成功通用回答。
- 同步根目录及两端 README/AGENTS；无数据库迁移、新依赖或新增环境变量。

## 测试与构建

| 验证 | 实际结果 |
| --- | --- |
| 后端新增自适应测试（三个文件） | 54 passed |
| 后端完整 `uv run pytest -q --tb=short --show-capture=no` | 1520 passed, 27 skipped，退出 0 |
| 前端 `npm run lint` | 退出 0，无警告 |
| 前端完整 `npm run test` | 60 文件，664 passed，退出 0 |
| 前端 `npm run build` | vue-tsc + Vite 均通过，退出 0 |
| 本次变更的 13 个 Python 文件 `ruff check` / `ruff format --check` | 全部通过 |
| 后端全量 `uv run ruff check .` | 39 条既有问题，退出 1 |
| 后端全量 `uv run ruff format --check .` | 6 个既有文件需格式化，退出 1 |
| `openspec validate add-adaptive-rag-answering --strict` | 通过 |
| `git diff --check` | 通过 |

全量后端静态检查未通过，不能称为所有质量门禁全绿。对 HEAD 的只读 `git archive` 快照运行相同工具，
当前 39 条问题均在基线复现，且全部来自本次未修改文件；格式化的 6 个文件集合与基线一致。
对比见 `baseline-comparison.json`、`baseline-ruff.log`、`baseline-format.log`。
未将这些存量问题混入本次行为变更。

日志入库时仅规整行尾空白，保留实际命令结果与失败信息。完整执行输出见 `backend-green.log`、`frontend-green.log`、`frontend-build.log`、
`backend-ruff.log`、`backend-format.log`。27 项跳过测试没有作为已通过测试统计。

初始 RED 证据保留在 `red-tests.md`。GREEN 复核期间新增的概念问题边界测试先出现 3 个预期失败；
合同/附件私有事实、删除和重分块缓存测试先出现 4 个预期失败，记录在 `edge-backend-red.log`。
来源展开断言先因“检索排名”展示失败，见 `edge-frontend-red.log`，修复后相关 26 项组件测试通过。

## 本地浏览器

真实 Chromium、Vue 页面及组件；在网络边界替换账号、资料列表和问答 API，未调用线上账户和模型。

```bash
cd front
npm run dev -- --host 127.0.0.1 --port 5176
```

另一终端运行（`ADAPTIVE_PLAYWRIGHT_PATH` 指向本机已安装的 Playwright 包）：

```bash
ADAPTIVE_PLAYWRIGHT_PATH=/path/to/playwright node openspec/changes/add-adaptive-rag-answering/evidence/verify-browser.cjs
```

8 项检查通过，浏览器未捕获异常为 0：欢迎页允许直接提问、通用回答、资料澄清、三文档总结、
部分覆盖、检索不可用、生成失败、390px 无横向溢出。来源展开可读，通用回答保留复制与真实用量字段，
澄清省略用量，总结来源显示片段顺序。报告与 7 张截图保存在同目录。
此验证只证明界面契约与交互，不证明真实模型回答质量或线上 demo 已生效。

## 交付边界

本记录对应本地实现与验证，未进行生产部署、归档或线上 demo 操作。
根据用户后续指令提交并推送本次变更，部署由用户自行完成。
后续部署需先发布兼容新字段的前端，再发布后端，并用实际 demo 模型配置进行问答与总结冒烟。
