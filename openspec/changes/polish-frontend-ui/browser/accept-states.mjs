import { launch, assert, screenshot, baseURL } from "./browser-helpers.mjs";
import { searchResponse } from "./fixtures.mjs";
const passed = [];
// 验证流程验证页保留真实的选择、结果展示和窄屏表格滚动能力。
{
  const { page, browser, errors } = await launch();
  try {
    await page.getByTestId("knowledge-count").waitFor();
    const knowledge = await page.getByTestId("knowledge-count").innerText();
    assert(
      knowledge.includes("2") &&
        knowledge.includes("已解析") &&
        !knowledge.includes("可检索"),
      "解析文档数不应伪称已可检索",
    );
    await page.goto(`${baseURL}/verify`);
    await page
      .getByTestId("document-select")
      .selectOption("6b45a493-45d2-4c13-9c39-a75efb98cefa");
    await page.getByTestId("verify-button").click();
    await page.getByTestId("verification-result").waitFor();
    assert(
      (await page.getByTestId("verification-summary").innerText()).includes(
        "7/7",
      ),
    );
    assert.equal(await page.getByTestId("pair-row").count(), 1);
    await screenshot(page, "after-verify");
    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      const size = await page.evaluate(() => ({
        w: innerWidth,
        scroll: document.documentElement.scrollWidth,
      }));
      assert(
        size.scroll <= size.w,
        `验证页 ${width}px 横向溢出：${JSON.stringify(size)}`,
      );
    }
    await screenshot(page, "after-verify-mobile");
    assert.deepEqual(errors, []);
    passed.push("verification-success-mobile");
  } finally {
    await browser.close();
  }
}
// 验证无文档时给出上传引导，保留返回问答的路径。
{
  const { page, browser, errors } = await launch(
    { width: 390, height: 844 },
    { emptyDocuments: true },
  );
  try {
    await page.goto(`${baseURL}/verify`);
    await page.getByTestId("documents-empty").waitFor();
    assert(
      (await page.getByTestId("documents-empty").innerText()).includes("上传"),
    );
    assert.equal(
      await page.getByTestId("verify-nav-back").getAttribute("href"),
      "/",
    );
    assert.deepEqual(errors, []);
    passed.push("verification-empty");
  } finally {
    await browser.close();
  }
}
// 验证搜索服务失败时用户能看到具体错误并能重新输入。
{
  const { page, browser, errors } = await launch(
    { width: 390, height: 844 },
    { searchError: true },
  );
  try {
    await page.getByTestId("chat-input").fill("查找资料中的关键结论");
    await page.getByTestId("chat-input").press("Enter");
    await page.getByTestId("chat-error").waitFor();
    assert(
      (await page.getByTestId("chat-error").innerText()).includes(
        "检索服务暂时不可用",
      ),
    );
    await page.getByTestId("chat-input").fill("重试查询");
    assert(!(await page.getByTestId("send-button").isDisabled()));
    await screenshot(page, "after-error");
    assert.deepEqual(errors, []);
    passed.push("search-error-recovery");
  } finally {
    await browser.close();
  }
}
// 验证无召回结果不会伪造来源，并保留减少动画偏好。
{
  const { page, browser, errors } = await launch();
  try {
    await page.route(`${baseURL}/api/search`, (r) =>
      r.fulfill({
        json: {
          ...searchResponse,
          results: [],
          answer: "根据现有文档内容，无法回答此问题。",
        },
      }),
    );
    await page.getByTestId("chat-input").fill("资料中没有描述的问题");
    await page.getByTestId("chat-input").press("Enter");
    await page.getByTestId("sources-empty").waitFor();
    assert(
      (await page.getByTestId("sources-empty").innerText()).includes(
        "缺少资料依据",
      ),
    );
    assert.equal(await page.getByTestId("source-item").count(), 0);
    const duration = await page
      .getByTestId("send-button")
      .evaluate((el) => getComputedStyle(el).transitionDuration);
    assert(
      duration.split(",").every((v) => parseFloat(v) <= 0.001),
      "减少动画偏好未生效",
    );
    assert.deepEqual(errors, []);
    passed.push("no-sources-reduced-motion");
  } finally {
    await browser.close();
  }
}
process.stdout.write(
  JSON.stringify({ result: "PASS", scenarios: passed }, null, 2),
);
