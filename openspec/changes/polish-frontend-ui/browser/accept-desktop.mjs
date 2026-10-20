import { launch, assert, screenshot } from "./browser-helpers.mjs";
const { page, browser, errors, requests } = await launch(
  { width: 1440, height: 1000 },
  { searchDelay: 700 },
);
try {
  // 验证新用户可以从欢迎页直接开始，并确认建议只填入、不自动发请求。
  assert(await page.getByTestId("send-button").isDisabled());
  await screenshot(page, "after-desktop");
  const suggestion = page
    .getByTestId("welcome-view")
    .getByRole("button")
    .filter({ hasText: "总结" })
    .first();
  await suggestion.click();
  assert((await page.getByTestId("chat-input").inputValue()).includes("总结"));
  assert(
    await page
      .getByTestId("chat-input")
      .evaluate((el) => el === document.activeElement),
  );
  assert.equal(requests.length, 0, "推荐问题不应自动发送");
  // 验证设置作用于下一条请求，Esc 关闭后焦点归还。
  await page.getByTestId("settings-button").click();
  const range = page
    .getByTestId("settings-popover")
    .locator('input[type="range"]');
  await range.fill("10");
  await range.dispatchEvent("input");
  await page.keyboard.press("Escape");
  assert.equal(await page.getByTestId("settings-popover").count(), 0);
  assert(
    await page
      .getByTestId("settings-button")
      .evaluate((el) => el === document.activeElement),
  );
  // 验证真实组件发送请求、禁用重复发送，并保留完整回答与可追溯来源。
  await page.getByTestId("chat-input").fill("如何建立可追溯的知识库？");
  await page.getByTestId("chat-input").press("Enter");
  assert(await page.getByTestId("send-button").isDisabled());
  await page.getByTestId("answer-content").waitFor();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].top_k, 10);
  assert(requests[0].session_id);
  const sourceItems = page.getByTestId("source-item");
  assert.equal(await sourceItems.count(), 2);
  assert.equal(
    await page
      .getByTestId("retrieval-details-toggle")
      .getAttribute("aria-expanded"),
    "false",
  );
  assert.equal(await page.getByTestId("results").count(), 0);
  await page.getByTestId("source-toggle").first().click();
  assert.equal(
    await sourceItems.first().getByTestId("source-chunk").count(),
    2,
  );
  assert(
    (await sourceItems.first().innerText()).includes(
      "团队需要定期检查知识库中的内容是否过时",
    ),
  );
  const lists = await page
    .getByTestId("answer-content")
    .locator("ol,ul")
    .evaluateAll((nodes) =>
      nodes.map((n) => [n.tagName, getComputedStyle(n).listStyleType]),
    );
  assert.deepEqual(lists, [
    ["OL", "decimal"],
    ["UL", "disc"],
  ]);
  await screenshot(page, "after-answer");
  // 验证检索详情仍保留所有诊断数据，来源和技术信息各自可达。
  await page.getByTestId("retrieval-details-toggle").click();
  assert.equal(await page.getByTestId("results").count(), 1);
  await page.getByTestId("results-toggle").click();
  assert.equal(await page.getByTestId("result-item").count(), 3);
  await page.getByTestId("prompt-toggle").click();
  assert(
    (await page.getByTestId("prompt").innerText()).includes(
      "请根据用户资料回答",
    ),
  );
  await screenshot(page, "after-details");
  // 验证多轮请求有同一会话标识和前一轮上下文，并且重复的来源区域没有重复 DOM ID。
  await page.getByTestId("chat-input").fill("这些资料有哪些共同点？");
  await page.getByTestId("chat-input").press("Enter");
  await page.getByTestId("answer-content").nth(1).waitFor();
  assert.equal(requests.length, 2);
  assert.equal(requests[1].session_id, requests[0].session_id);
  assert.equal(requests[1].history.length, 2);
  assert.equal(requests[1].history[0].content, "如何建立可追溯的知识库？");
  await page.getByTestId("source-toggle").nth(2).click();
  await page.getByTestId("retrieval-details-toggle").nth(1).click();
  const repeated = await page.locator("[id]").evaluateAll((nodes) => {
    const seen = new Set();
    return nodes.map((n) => n.id).filter((id) => seen.has(id) || !seen.add(id));
  });
  assert.deepEqual(repeated, [], "多轮对话中 DOM id 应保持唯一");
  // 验证会话刷新、重命名、新建、切换和删除确认仍正常工作。
  await page.getByTestId("top-nav-title").click();
  await page.getByTestId("top-nav-title-input").fill("知识库建设笔记");
  await page.getByTestId("top-nav-title-input").press("Enter");
  await page.reload();
  await page.getByTestId("answer-content").nth(1).waitFor();
  assert(
    (await page.getByTestId("top-nav-title").innerText()).includes(
      "知识库建设笔记",
    ),
  );
  await page.getByTestId("new-conversation-btn").click();
  await page.getByTestId("welcome-view").waitFor();
  assert.equal(await page.getByTestId("conversation-item").count(), 2);
  await page
    .getByTestId("conversation-select")
    .filter({ hasText: "知识库建设笔记" })
    .click();
  await page.getByTestId("answer-content").nth(1).waitFor();
  const active = page
    .getByTestId("conversation-item")
    .filter({ hasText: "知识库建设笔记" });
  await active.getByTestId("delete-conversation-btn").click();
  await page.getByRole("dialog").waitFor();
  assert(
    await page
      .getByTestId("confirm-dialog-cancel-btn")
      .evaluate((el) => el === document.activeElement),
  );
  await page.getByTestId("confirm-dialog-cancel-btn").click();
  assert.equal(await page.getByTestId("conversation-item").count(), 2);
  await active.getByTestId("delete-conversation-btn").click();
  await page.getByTestId("confirm-dialog-confirm-btn").click();
  assert.equal(await page.getByTestId("conversation-item").count(), 1);
  assert.deepEqual(errors, []);
  process.stdout.write(
    JSON.stringify(
      {
        result: "PASS",
        scenarios: 12,
        requests: requests.length,
        markdown: lists,
        pageErrors: errors,
      },
      null,
      2,
    ),
  );
} finally {
  await browser.close();
}
