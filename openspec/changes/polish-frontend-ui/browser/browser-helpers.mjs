import { mkdir } from "node:fs/promises";
import { join } from "node:path";
const { chromium } = await import(
  process.env.KNOWRA_PLAYWRIGHT_MODULE || "playwright"
);
import { user, documents, searchResponse, verification } from "./fixtures.mjs";
import assert from "node:assert/strict";
export { assert };
export const baseURL = (
  process.env.KNOWRA_ACCEPTANCE_URL || "http://localhost:5173"
).replace(/\/$/, "");
export const root =
  process.env.KNOWRA_ACCEPTANCE_OUTPUT || "/tmp/knowra-frontend-acceptance";
export async function launch(
  viewport = { width: 1440, height: 1000 },
  options = {},
) {
  const browser = await chromium.launch({
    headless: true,
    args: ["--no-sandbox"],
  });
  const context = await browser.newContext({
    viewport,
    deviceScaleFactor: 1,
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  const errors = [];
  const requests = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("https://**/*", (route) => route.abort());
  // 限定 API 路径，避免拦截 Vite 的 /src/api/ 模块。
  await page.route(`${baseURL}/api/**`, async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === "/api/users/me") return route.fulfill({ json: user });
    if (path === "/api/parsed-documents")
      return route.fulfill({
        json: options.emptyDocuments ? [] : documents.items,
      });
    if (path === "/api/search") {
      const request = route.request().postDataJSON();
      requests.push(request);
      if (options.searchDelay)
        await new Promise((resolve) =>
          setTimeout(resolve, options.searchDelay),
        );
      return options.searchError
        ? route.fulfill({
            status: 503,
            json: { detail: "检索服务暂时不可用，请稍后重试。" },
          })
        : route.fulfill({ json: { ...searchResponse, query: request.query } });
    }
    if (path.endsWith("/pipeline-verification"))
      return options.verifyError
        ? route.fulfill({
            status: 404,
            json: { detail: "该文档尚未完成向量化，请完成资料处理后重试。" },
          })
        : route.fulfill({ json: verification });
    if (path === "/api/uploads")
      return route.fulfill({
        json: {
          id: "acceptance-upload",
          owner_user_id: user.id,
          original_filename: "acceptance.md",
          content_type: "text/markdown",
          byte_size: 50,
          storage_key: "acceptance",
          checksum_sha256: "abc",
          status: "uploaded",
          created_at: "2026-10-20T00:00:00Z",
        },
      });
    return route.fulfill({
      status: 404,
      json: { detail: `本地验收数据未定义此接口：${path}` },
    });
  });
  await page.goto(baseURL);
  await page.getByTestId("welcome-view").waitFor();
  return { browser, context, page, errors, requests };
}
export async function screenshot(page, name) {
  await mkdir(root, { recursive: true });
  await page.screenshot({
    path: join(root, `${name}.png`),
    fullPage: true,
    animations: "disabled",
  });
}
export async function assertFits(page, label) {
  const dimensions = await page.evaluate(() => ({
    viewport: innerWidth,
    content: document.documentElement.scrollWidth,
  }));
  assert(
    dimensions.content <= dimensions.viewport,
    `${label} 页面水平溢出：${JSON.stringify(dimensions)}`,
  );
  const input = await page.getByTestId("chat-input").boundingBox();
  assert(
    input && input.width >= (dimensions.viewport === 320 ? 240 : 300),
    `${label} 输入框宽度不足：${JSON.stringify(input)}`,
  );
  const send = await page.getByTestId("send-button").boundingBox();
  assert(
    send && send.x >= 0 && send.x + send.width <= dimensions.viewport,
    `${label} 发送按钮超出视口`,
  );
}
