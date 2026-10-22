import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

const READONLY_HINT = "只读账号不能上传或处理资料"

describe("只读用户的上传入口", () => {
  // 测试：ChatInput 在不可上传时禁用附件按钮并给出可读说明（读屏可通过 aria-describedby 获取）。
  it("ChatInput canUpload=false 时禁用附件按钮并说明原因", async () => {
    const { default: ChatInput } = await import("../ChatInput.vue")
    const wrapper = mount(ChatInput, {
      props: {
        modelValue: "",
        topK: 5,
        loading: false,
        files: [],
        canUpload: false,
      },
      attachTo: document.body,
    })

    const attach = wrapper.find('[data-testid="attach-button"]')
    expect(attach.attributes("disabled")).toBeDefined()
    const describedBy = attach.attributes("aria-describedby")
    expect(describedBy).toBeTruthy()
    expect(document.getElementById(describedBy!)?.textContent).toContain(
      READONLY_HINT,
    )
    wrapper.unmount()
  })

  // 测试：默认（可上传）时附件按钮可用，不显示只读说明。
  it("ChatInput 默认可上传", async () => {
    const { default: ChatInput } = await import("../ChatInput.vue")
    const wrapper = mount(ChatInput, {
      props: { modelValue: "", topK: 5, loading: false, files: [] },
    })

    expect(
      wrapper.find('[data-testid="attach-button"]').attributes("disabled"),
    ).toBeUndefined()
    expect(wrapper.text()).not.toContain(READONLY_HINT)
  })

  // 测试：欢迎页的“上传资料”在只读时禁用并显示说明，不触发 upload 事件。
  it("WelcomeView canUpload=false 时禁用上传资料", async () => {
    const { default: WelcomeView } = await import("../chat/WelcomeView.vue")
    const wrapper = mount(WelcomeView, { props: { canUpload: false } })

    const upload = wrapper.find('[data-testid="welcome-upload"]')
    expect(upload.attributes("disabled")).toBeDefined()
    await upload.trigger("click")
    expect(wrapper.emitted("upload")).toBeUndefined()
    expect(wrapper.text()).toContain(READONLY_HINT)
  })
})
