import { launch, assert, screenshot } from "./browser-helpers.mjs";
const { page, browser, errors, requests } = await launch(
  { width: 390, height: 844 },
  { searchDelay: 500 },
);
async function latestGeometry() {
  return page
    .getByTestId("answer-content")
    .last()
    .evaluate((answer) => {
      const scroll = answer.closest(".overflow-y-auto");
      const a = answer.getBoundingClientRect(),
        s = scroll.getBoundingClientRect();
      return {
        answerTop: a.top,
        answerBottom: a.bottom,
        viewportTop: s.top,
        viewportBottom: s.bottom,
        scrollTop: scroll.scrollTop,
      };
    });
}
try {
  const input = page.getByTestId("chat-input");
  for (let i = 0; i < 2; i++) {
    await input.fill(`第${i + 1}个验收问题`);
    await input.press("Enter");
    await page.getByTestId("answer-content").nth(i).waitFor();
  }
  const second = await latestGeometry();
  assert(
    second.answerTop >= second.viewportTop - 1 &&
      second.answerTop < second.viewportBottom - 30,
    `第二轮回答开头不在可见区域：${JSON.stringify(second)}`,
  );
  await screenshot(page, "after-mobile-conversation");
  // 用户在等待回答时回看前文，响应完成不能把阅读位置拉走。
  await input.fill("第三个验收问题");
  await input.press("Enter");
  await page.getByTestId("answer-pending").waitFor();
  await page
    .getByTestId("answer-content")
    .first()
    .evaluate((answer) => {
      answer.closest(".overflow-y-auto").scrollTop = 0;
    });
  await page.getByTestId("answer-content").nth(2).waitFor();
  assert.equal(
    (await latestGeometry()).scrollTop,
    0,
    "异步回答完成时打断了用户回看前文",
  );
  // 中文输入法确认候选词时不能误发送。
  await input.fill("如何");
  const before = requests.length;
  await input.dispatchEvent("compositionstart");
  await input.dispatchEvent("keydown", {
    key: "Enter",
    code: "Enter",
    isComposing: true,
  });
  await page.waitForTimeout(150);
  assert.equal(requests.length, before, "中文输入法确认候选词时误发送");
  assert.equal(await input.inputValue(), "如何", "中文输入法候选确认丢失草稿");
  await input.dispatchEvent("compositionend", { data: "如何" });
  await input.press("Enter");
  await page.getByTestId("answer-content").nth(3).waitFor();
  assert.equal(requests.length, before + 1, "普通 Enter 未发送");
  assert.deepEqual(errors, []);
  process.stdout.write(
    JSON.stringify(
      {
        result: "PASS",
        scenarios: [
          "new-turn-visible",
          "preserve-reading-position",
          "ime-enter",
          "ordinary-enter",
        ],
        secondTurn: second,
        pageErrors: errors,
      },
      null,
      2,
    ),
  );
} finally {
  await browser.close();
}

// 普通动画模式下，消息滚动不能移动应用壳层与固定输入区。
const normal = await launch({ width: 390, height: 844 }, { searchDelay: 500 });
try {
  await normal.page.emulateMedia({ reducedMotion: "no-preference" });
  for (let i = 0; i < 3; i++) {
    await normal.page.getByTestId("chat-input").fill(`普通动画第${i + 1}问`);
    await normal.page.getByTestId("chat-input").press("Enter");
    await normal.page.getByTestId("answer-content").nth(i).waitFor();
    await normal.page.waitForTimeout(600);
    const rects = await normal.page
      .getByTestId("answer-content")
      .last()
      .evaluate((answer) => {
        const scroll = answer
          .closest(".overflow-y-auto")
          .getBoundingClientRect();
        return {
          scrollTop: scroll.top,
          headerTop: document.querySelector("header").getBoundingClientRect()
            .top,
        };
      });
    assert.equal(
      rects.headerTop,
      0,
      `普通动画第${i + 1}轮把顶栏滚出了视口：${JSON.stringify(rects)}`,
    );
    assert(
      rects.scrollTop >= 51,
      `消息滚动移动了应用壳层：${JSON.stringify(rects)}`,
    );
  }
  await screenshot(normal.page, "after-mobile-motion");
  assert.deepEqual(normal.errors, []);
  process.stdout.write(
    JSON.stringify(
      {
        result: "PASS",
        scenarios: ["normal-motion-shell-stable"],
        turns: 3,
        pageErrors: normal.errors,
      },
      null,
      2,
    ),
  );
} finally {
  await normal.browser.close();
}
