# 前端重构验收报告

验收日期：2026-10-20。设计与生产代码实现：pi / `dtmaas/claude-opus-5-5`。独立评审与验收：Codex。

## 结论

本变更通过前端验收，覆盖当前路由 `/` 和 `/verify`。视觉采用「书房批注本」：暖纸背景、松烟青操作、朱砂来源标记、本地中文字体回退，围绕「上传资料 → 提问 → 核对来源」组织页面。

验收时的工作区原本已有未提交的前端修改。本次在这些修改基础上继续实现；后端没有改动，API 与 localStorage 会话结构保持兼容。本报告记录提交前的验收结果；本次交付同步主规范并提交、推送代码，不涉及部署或归档。

## 自动化质量检查

以下命令由 Codex 在 `front/` 中独立执行，均以退出码 0 完成：

| 命令 | 实际结果 | 证据 |
| --- | --- | --- |
| `npm run lint` | ESLint 通过 | [lint 输出](evidence/codex-lint.txt) |
| `npm run test` | 36 个测试文件、471 个用例全部通过，无未处理异常 | [测试输出](evidence/codex-test.txt) |
| `npm run build` | TypeScript 检查与 Vite 构建通过，103 个模块 | [构建输出](evidence/codex-build.txt) |
| `git diff --cached --check` 与文档完整性检查 | 通过；53 项任务完成，主规范同步一致，相对链接完整 | [文档与暂存检查](evidence/codex-document-checks.txt) |
| `openspec validate polish-frontend-ui --strict` | `Change 'polish-frontend-ui' is valid` | [本次规范校验](evidence/codex-openspec-scope.txt) |
| 两份主规范分别 `validate --type spec --strict` | `frontend-redesign` 与 `chat-recall-ui` 均通过 | [本次规范校验](evidence/codex-openspec-scope.txt) |

额外执行全库 `openspec validate --all --strict --no-interactive`，结果为 18 项通过、1 项失败，详见 [全库校验输出](evidence/codex-openspec.txt)。失败来自已有 `query-rewriting-integration` 的“回溯限制”需求缺少 `#### Scenario`。已逐字节确认该规范与提交前 HEAD 一致，本次未修改；这不影响本次变更及两份受影响主规范的严格校验结果。

基线为 345 个测试用例通过。本次先增加失败测试、确认 RED，再实现功能；初始完整行为 RED 为 104 个失败、359 个通过。后续评审发现的问题也经过回归测试与浏览器复现后修复，过程记录见 [RED 证据](evidence/red-evidence.md)。最终验证消除了 jsdom 缺少滚动 API 导致的未处理异常，没有把“断言通过但仍有异常”的运行算作通过。

## 浏览器验收

Codex 使用真实 Chromium 与真实 Vue 组件，在本地 Vite 服务上执行独立 Playwright 脚本。API 使用隔离的验收夹具；外部 HTTPS 请求被阻止，页面仍能正常显示。

| 脚本 | 验收内容与实际结果 |
| --- | --- |
| `accept-desktop.mjs` | 12 组检查通过：推荐问题只填入并聚焦、空输入禁发、检索设置进入请求、发送中禁用、来源聚合与原文、默认收纳诊断、多轮 history/session_id、跨轮唯一 ID、重命名与刷新持久化、新建/切换/删除确认 |
| `accept-mobile.mjs` | 390px / 320px 通过：输入区宽度、菜单与标题无重叠、发送按钮可见、关闭抽屉不可 Tab 进入、抽屉焦点循环与归还、选择当前对话也收起、嵌套确认框 Tab/Shift+Tab/Esc、真实文件选择入口与上传成功反馈 |
| `accept-states.mjs` | 通过：流程验证成功与空状态、长文件名和 UUID 在窄屏不撑破页面、搜索错误与恢复输入、无来源时明确提示、减少动画偏好 |
| `accept-composer.mjs` | 通过：追问开头进入视野、异步回答不打断向上阅读、中文输入法 Enter 不误发送、普通 Enter 仍发送、普通动画下连续三轮提问保持顶栏与应用壳稳定 |

浏览器日志：[桌面](evidence/codex-browser-desktop.txt)、[移动端](evidence/codex-browser-mobile.txt)、[页面状态](evidence/codex-browser-states.txt)、[输入与滚动](evidence/codex-browser-composer.txt)。所有脚本最终退出码为 0，均没有浏览器页面异常。

关键实测值：

| 检查项 | 实际结果 |
| --- | --- |
| 390px 文本输入区 | 364px；重构前约 164px |
| 390px 顶栏 | 菜单右边界 48px，标题左边界 56px，没有重叠 |
| 320px 主页面和验证页 | `scrollWidth ≤ viewportWidth`，没有整页横向溢出 |
| Markdown 有序 / 无序列表 | computed `list-style-type` 分别为 `decimal` / `disc` |
| 减少动画 | computed `transition-duration ≤ 0.001s` |
| 手机检索设置 | 弹层 x=63px、宽 256px，完整位于 390px 视口内 |

## 评审中要求返修的问题

1. 在移动抽屉中按 Esc 取消删除时，底层抽屉也关闭。修复后只关闭最上层确认框并归还焦点，再按一次 Esc 才关闭抽屉；自然 Tab 移动与两端循环均可用。
2. 连续提问后新问答完全位于视口之外。增加主动发送后的消息区滚动，异步响应不强制移动阅读位置。
3. 最初的 `scrollIntoView` 修复会在普通动画下滚动外层应用壳，实测第三轮顶栏 y=-518px。最终只调用消息容器的 `scrollTo`，顶栏保持在 y=0。
4. 中文输入法确认候选词的 Enter 会误发送。最终在 `isComposing` 或 keyCode 229 时保留草稿，不发送。
5. 同步调整主工具栏文案为「检索 N 段」，Top-K 留在设置弹层中，并修正重复 ARIA ID、嵌套按钮与全局监听器测试清理等问题。

评审后同时校正文档中残留的旧上传、解析轮询和重新分块 UI 描述，使其符合当前主界面的实际行为。

## 截图

截图中的用户、资料名称、模型名和回答来自验收夹具。

- [桌面欢迎页](screenshots/desktop.png)
- [回答与原文来源](screenshots/conversation.png)
- [390px 手机界面](screenshots/mobile.png)
- [320px 手机界面](screenshots/mobile-320.png)
- [检索设置](screenshots/settings.png)
- [手机检索设置](screenshots/settings-mobile.png)
- [手机导航抽屉](screenshots/mobile-drawer.png)
- [流程验证页](screenshots/verification.png)
- [窄屏流程验证页](screenshots/verification-mobile.png)
- [重构前桌面](screenshots/before-desktop.png)
- [重构前手机](screenshots/before-mobile.png)

## 范围与复现

浏览器验收验证前端组件、API 请求参数和响应展示。文件选择使用真实浏览器 `filechooser`，上传与问答接口响应使用 mock；本报告不代表真实后端解析、索引、文件存储或模型生成已经联调通过，也没有评估检索质量。

浏览器脚本与夹具已保存于 [browser/](browser/README.md)，支持通过环境变量配置前端地址、Playwright 模块路径和截图输出目录。复现步骤见该目录的说明；无需依赖原工作机的临时脚本或缓存路径。

## OpenSpec 与交付完整性

- `proposal.md`、`design.md`、两份增量规范及 `tasks.md` 已覆盖最终实现。
- 已将 `frontend-redesign` 与 `chat-recall-ui` 的变更同步到主规范，保留路由壳、会话持久化、错误反馈等未受影响的要求。
- 主规范同步包括语义视觉令牌、资料库已解析数量、移动抽屉与删除确认、输入法保护、附件发送条件、来源聚合及默认折叠的检索详情。
- 验收日志使用 `.txt` 保存，避免仓库的 `*.log` 忽略规则遗漏交付证据；RED 的原始输出也已保存并由摘要链接。
- 变更保持在 `openspec/changes/polish-frontend-ui/`，未归档。临时 `.playwright-mcp/` 和仓库根目录的两张试验截图不属于本次提交。
