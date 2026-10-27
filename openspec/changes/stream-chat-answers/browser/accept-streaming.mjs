import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { user, documents, searchResponse } from "../../polish-frontend-ui/browser/fixtures.mjs";

const { chromium } = await import(process.env.KNOWRA_PLAYWRIGHT_MODULE || "playwright");
const origin = process.env.KNOWRA_ACCEPTANCE_URL || "http://127.0.0.1:5173";
const output = fileURLToPath(new URL("../evidence/browser/", import.meta.url));
const sessions = [];
const server = createServer((request, response) => {
  response.setHeader("Access-Control-Allow-Origin", origin);
  response.setHeader("Access-Control-Allow-Credentials", "true");
  response.setHeader("Access-Control-Allow-Headers", "Content-Type, X-Trace-ID");
  response.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  if (request.method === "OPTIONS") {
    response.writeHead(204);
    response.end();
    return;
  }
  let body = "";
  request.on("data", (chunk) => { body += chunk; });
  request.on("end", () => {
    assert(request.headers.accept.includes("text/event-stream"), "前端必须协商真实 SSE");
    const final = {
      ...searchResponse, query: JSON.parse(body).query,
      answer_mode: "rag", retrieval_status: "matched", answer_incomplete: false,
    };
    const event = (name, data) => response.write(`event: ${name}\ndata: ${JSON.stringify(data)}\n\n`);
    const session = {
      response, closed: false, text: "",
      delta(text) { this.text += text; event("delta", { delta: text }); },
      done() { event("done", { ...final, answer: this.text }); response.end(); },
    };
    response.on("close", () => { session.closed = true; });
    sessions.push(session);
    response.writeHead(200, {
      "Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-cache",
    });
    event("status", { stage: "searching" });
    event("status", { stage: "generating" });
    event("metadata", { ...final, answer: "", answer_tokens: null });
  });
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const streamURL = `http://127.0.0.1:${server.address().port}/search`;
let browser;
const results = [];
try {
  browser = await chromium.launch({
    headless: true,
    ...(process.env.KNOWRA_CHROMIUM_PATH ? { executablePath: process.env.KNOWRA_CHROMIUM_PATH } : {}),
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 }, reducedMotion: "no-preference",
  });
  const page = await context.newPage();
  page.setDefaultTimeout(8000);
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("https://**/*", (route) => route.abort());
  await page.route(`${origin}/api/**`, async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/users/me") return route.fulfill({
      json: { ...user, id: "streaming-browser-fixture", role: "member", permissions: ["knowledge:read", "knowledge:write"] },
    });
    if (path === "/api/parsed-documents") return route.fulfill({ json: documents.items });
    if (path === "/api/search") return route.continue({ url: streamURL });
    return route.fulfill({ status: 404, json: { detail: "未定义的浏览器验收接口" } });
  });
  await mkdir(output, { recursive: true });
  await page.goto(origin);
  await page.getByTestId("welcome-view").waitFor();

  async function ask(text) {
    await page.getByTestId("chat-input").fill(text);
    await page.getByTestId("chat-input").press("Enter");
    await page.locator('[data-testid="answer-panel"][aria-busy="true"]').waitFor();
    return sessions.at(-1);
  }
  async function textVisible(text) {
    await page.waitForFunction((value) => [...document.querySelectorAll('[data-testid="answer-content"]')]
      .some((element) => element.textContent.includes(value)), text);
  }
  async function assertFits() {
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "页面不能水平溢出");
    assert(await page.getByTestId("chat-input").isVisible(), "输入区应保持可见");
  }

  // 验证真实 HTTP 流未结束时正文、来源、光标和生成状态已显示，不能重复发送。
  const first = await ask("如何建立可追溯的知识库？");
  first.delta("## 建立可追溯的知识库\n\n先保留资料来源，再组织和检索内容。[1]\n\n");
  await textVisible("先保留资料来源");
  assert(await page.getByTestId("streaming-cursor").isVisible());
  assert(await page.getByTestId("chat-input").isDisabled());
  assert(await page.getByTestId("source-list").isVisible());
  assert.equal(first.closed, false, "首段必须在 HTTP 流结束前可读");
  const animation = await page.getByTestId("streaming-cursor").evaluate((element) => getComputedStyle(element).animationName);
  assert.notEqual(animation, "none");
  await assertFits();
  await page.screenshot({ path: `${output}/streaming-desktop.png` });
  results.push({ scenario: "real-http-sse-before-done", animation, passed: true });

  // 验证长回答可跟随到底部，用户回看前文后新增正文不会抢走阅读位置或移动外层壳。
  first.delta("知识库应保留来源和维护记录，回答需要引用原文。\n\n".repeat(80));
  await textVisible("维护记录");
  await page.getByTestId("chat-scroll").evaluate((element) => { element.scrollTop = 0; });
  first.delta("末尾补充：定期核对资料版本。\n");
  await textVisible("末尾补充");
  assert.equal(await page.getByTestId("chat-scroll").evaluate((element) => element.scrollTop), 0);
  assert.equal(await page.evaluate(() => document.querySelector("header").getBoundingClientRect().top), 0);
  first.done();
  await page.getByTestId("streaming-cursor").waitFor({ state: "hidden" });
  assert(await page.getByTestId("chat-input").isEnabled());
  assert((await page.getByTestId("token-total").innerText()).includes("860"));
  results.push({ scenario: "preserve-reading-position-and-final-usage", passed: true });

  // 验证窄屏与减少动态效果：保留静态状态和真实 Markdown，关闭闪烁与位移。
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const second = await ask("请列出整理资料的步骤");
  second.delta("可以按以下顺序整理：\n\n1. **接入资料**，保留文件名和页码。\n2. **核对来源**，展开原文片段。[1]\n");
  await textVisible("可以按以下顺序整理");
  assert.equal(await page.getByTestId("streaming-cursor").evaluate((element) => getComputedStyle(element).animationName), "none");
  assert.equal(await page.getByTestId("answer-content").last().evaluate((element) => getComputedStyle(element).animationName), "none");
  await assertFits();
  await page.screenshot({ path: `${output}/streaming-mobile-reduced-motion.png` });
  second.done();
  await page.getByTestId("streaming-cursor").waitFor({ state: "hidden" });
  results.push({ scenario: "mobile-reduced-motion-and-markdown", width: 390, passed: true });

  // 验证真实 TCP 断流保留正文与来源、提示未完成，并恢复输入。
  const third = await ask("断流恢复验收");
  third.delta("这段正文应在断流后保留。\n");
  await textVisible("这段正文应在断流后保留");
  third.response.destroy();
  await page.getByTestId("answer-incomplete").waitFor();
  assert((await page.getByTestId("answer-content").last().innerText()).includes("这段正文应在断流后保留"));
  assert(await page.getByTestId("chat-input").isEnabled());
  assert.equal(await page.getByTestId("streaming-cursor").count(), 0);
  results.push({ scenario: "tcp-interruption-keeps-partial-answer", passed: true });

  // 验证 Vue 路由卸载取消真实 HTTP 流，不遗留连接。
  await page.setViewportSize({ width: 1440, height: 1000 });
  const fourth = await ask("取消连接验收");
  fourth.delta("离开问答页面时应停止生成。\n");
  await textVisible("离开问答页面时应停止生成");
  await page.getByTestId("user-menu-button").click();
  await page.getByTestId("menu-account").click();
  await page.waitForURL("**/account");
  await page.waitForTimeout(100);
  assert(fourth.closed, "路由卸载必须取消供应商连接");
  assert.deepEqual(errors, [], "浏览器不能有未处理异常");
  results.push({ scenario: "route-unmount-aborts-http-stream", passed: true });
  process.stdout.write(JSON.stringify({ result: "PASS", scenarios: results, pageErrors: errors }, null, 2) + "\n");
} finally {
  await browser?.close();
  server.closeAllConnections();
  await new Promise((resolve) => server.close(resolve));
}
