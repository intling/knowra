# 浏览器验收复现

这些脚本用真实 Chromium 验证前端交互与布局，`fixtures.mjs` 提供虚构用户、文档、问答及流程验证响应。它们不连接真实后端，也不验证实际解析、索引或模型质量。脚本通过标准输出报告断言结果，不接入应用的运行时日志。

在仓库根目录的一个终端启动前端：

```bash
npm --prefix front run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

在另一个终端准备独立的验收工具目录。Playwright 不加入应用依赖：

```bash
npm install --prefix /tmp/knowra-browser-tools --no-save --package-lock=false playwright@1.63.0-alpha-2026-08-05
node /tmp/knowra-browser-tools/node_modules/playwright/cli.js install chromium
export KNOWRA_PLAYWRIGHT_MODULE=/tmp/knowra-browser-tools/node_modules/playwright/index.mjs
```

在仓库根目录执行：

```bash
node openspec/changes/polish-frontend-ui/browser/accept-desktop.mjs
node openspec/changes/polish-frontend-ui/browser/accept-mobile.mjs
node openspec/changes/polish-frontend-ui/browser/accept-states.mjs
node openspec/changes/polish-frontend-ui/browser/accept-composer.mjs
```

四个脚本均应退出 0 并输出 `PASS`。环境变量：

| 变量                       | 默认值                            | 用途                                                     |
| -------------------------- | --------------------------------- | -------------------------------------------------------- |
| `KNOWRA_PLAYWRIGHT_MODULE` | `playwright`                      | 可选的 Playwright 模块绝对路径；已有可解析安装时可以省略 |
| `KNOWRA_ACCEPTANCE_URL`    | `http://localhost:5173`           | 被验收的本地前端地址，API 必须同源且使用 `/api` 前缀     |
| `KNOWRA_ACCEPTANCE_OUTPUT` | `/tmp/knowra-frontend-acceptance` | 本次执行的截图输出目录，不覆盖已保存的验收截图           |

使用独立浏览器上下文避免读写个人会话。API 路由仅拦截 `${KNOWRA_ACCEPTANCE_URL}/api/**`；不要改为 `**/api/**`，否则会拦截 Vite 的 `/src/api/` 源码模块。脚本阻止外部 HTTPS 请求；每组检查结束后关闭浏览器。

对应的最终输出见 [桌面](../evidence/codex-browser-desktop.txt)、[移动端](../evidence/codex-browser-mobile.txt)、[页面状态](../evidence/codex-browser-states.txt)、[输入与滚动](../evidence/codex-browser-composer.txt)。
