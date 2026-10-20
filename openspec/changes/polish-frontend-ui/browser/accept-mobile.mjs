import { launch, assert, screenshot, assertFits } from "./browser-helpers.mjs";
const { page, browser, errors } = await launch(
  { width: 390, height: 844 },
  { emptyDocuments: true },
);
try {
  // 验证 390px 下输入宽度、菜单标题布局与整页横向溢出。
  await assertFits(page, "390px");
  const promptWidth390 = (await page.getByTestId("chat-input").boundingBox())
    .width;
  const menu = page.getByTestId("hamburger-menu");
  const title = page.getByTestId("top-nav-title");
  const mb = await menu.boundingBox(),
    tb = await title.boundingBox();
  assert(mb && tb && mb.x + mb.width <= tb.x, "菜单按钮与标题重叠");
  await screenshot(page, "after-mobile");
  const drawer = page.getByTestId("mobile-sidebar");
  assert(await drawer.evaluate((el) => el.inert), "关闭抽屉必须 inert");
  // 验证关闭抽屉不会泄漏不可见的键盘停靠点。
  await page.getByTestId("chat-input").focus();
  for (let i = 0; i < 14; i++) {
    await page.keyboard.press("Tab");
    assert(
      !(await page.evaluate(
        () =>
          !!document.activeElement.closest('[data-testid="mobile-sidebar"]'),
      )),
      "Tab 进入了关闭抽屉",
    );
  }
  // 验证打开抽屉后焦点在内部循环，Esc 关闭并归还焦点。
  await menu.click();
  assert.equal(await menu.getAttribute("aria-expanded"), "true");
  assert(await drawer.evaluate((el) => el.contains(document.activeElement)));
  const controls = drawer.locator(
    'button:not([disabled]),a[href],input:not([disabled]),[tabindex="0"]',
  );
  const first = controls.first(),
    last = controls.last();
  await last.focus();
  await page.keyboard.press("Tab");
  assert(
    await first.evaluate((el) => el === document.activeElement),
    "导航抽屉最后一个控件 Tab 后应回到第一个",
  );
  await page.keyboard.press("Shift+Tab");
  assert(
    await last.evaluate((el) => el === document.activeElement),
    "导航抽屉第一个控件 Shift+Tab 后应回到最后一个",
  );
  await page.keyboard.press("Escape");
  assert(await drawer.evaluate((el) => el.inert));
  assert(await menu.evaluate((el) => el === document.activeElement));
  // 验证新建对话和选择当前对话这两个操作都会收起抽屉。
  await menu.click();
  await drawer.getByTestId("new-conversation-btn").click();
  assert(await drawer.evaluate((el) => el.inert), "新建对话应收起导航");
  await menu.click();
  await drawer.getByTestId("conversation-select").first().click();
  assert(await drawer.evaluate((el) => el.inert), "选择当前对话也应收起导航");
  // 验证抽屉中打开的确认框独立管理焦点，Esc 只取消最上层确认框。
  await menu.click();
  await drawer.getByTestId("delete-conversation-btn").first().click();
  const confirmation = page
    .getByTestId("confirm-dialog-overlay")
    .getByRole("dialog");
  await confirmation.waitFor();
  await page.keyboard.press("Tab");
  assert(
    await confirmation.evaluate((el) => el.contains(document.activeElement)),
    "删除确认框的焦点被背景抽屉抢走",
  );
  assert(
    await page
      .getByTestId("confirm-dialog-confirm-btn")
      .evaluate((el) => el === document.activeElement),
    "取消按钮按 Tab 后应移到删除按钮",
  );
  await page.keyboard.press("Tab");
  assert(
    await page
      .getByTestId("confirm-dialog-cancel-btn")
      .evaluate((el) => el === document.activeElement),
    "删除按钮按 Tab 后应循环回取消按钮",
  );
  await page.keyboard.press("Shift+Tab");
  assert(
    await page
      .getByTestId("confirm-dialog-confirm-btn")
      .evaluate((el) => el === document.activeElement),
    "取消按钮按 Shift+Tab 后应循环到删除按钮",
  );
  await page.keyboard.press("Escape");
  assert.equal(await page.getByTestId("confirm-dialog-overlay").count(), 0);
  assert(
    !(await drawer.evaluate((el) => el.inert)),
    "取消删除后应保留已打开的导航抽屉",
  );
  await page.keyboard.press("Escape");
  assert(await drawer.evaluate((el) => el.inert));
  // 验证欢迎页上传入口复用实际文件选择，文件上传后可继续提问。
  const chooser = page.waitForEvent("filechooser");
  await page
    .getByTestId("welcome-view")
    .getByRole("button", { name: "上传资料", exact: true })
    .click();
  await (
    await chooser
  ).setFiles({
    name: "acceptance.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("# 验收资料\n知识来自原始资料。"),
  });
  await page.getByTestId("file-chip-success").waitFor();
  await screenshot(page, "after-mobile-upload");
  // 验证更窄屏幕下所有主要操作仍在视口内。
  await page.setViewportSize({ width: 320, height: 740 });
  await assertFits(page, "320px");
  await screenshot(page, "after-mobile-320");
  assert.deepEqual(errors, []);
  process.stdout.write(
    JSON.stringify(
      {
        result: "PASS",
        viewports: [390, 320],
        promptWidth390,
        pageErrors: errors,
      },
      null,
      2,
    ),
  );
} finally {
  await browser.close();
}
