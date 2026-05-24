import { mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import { beforeEach, describe, expect, it, vi } from "vitest"

import HomeView from "./HomeView.vue"

const refreshHealthMock = vi.fn()
const loadCurrentUserMock = vi.fn()

vi.mock("../stores/app", () => ({
  useAppStore: () => ({
    health: {
      status: "ok",
      environment: "local",
    },
    isHealthLoading: false,
    healthError: null,
    lastHealthCheckedAt: null,
    refreshHealth: refreshHealthMock,
  }),
}))

vi.mock("../stores/user", () => ({
  useUserStore: () => ({
    currentUser: {
      display_name: "Default User",
    },
    isUserLoading: false,
    userError: null,
    loadCurrentUser: loadCurrentUserMock,
  }),
}))

describe("HomeView", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    refreshHealthMock.mockReset()
    loadCurrentUserMock.mockReset()
  })

  it("shows current user context without authentication actions", () => {
    const wrapper = mount(HomeView)
    const text = wrapper.text()

    expect(text).toContain("Default User")
    expect(text).not.toContain("\u767b\u5f55")
    expect(text).not.toContain("\u6ce8\u518c")
    expect(text).not.toContain("\u9000\u51fa")
    expect(text).not.toContain("\u5207\u6362\u7528\u6237")
    expect(loadCurrentUserMock).toHaveBeenCalledOnce()
  })

  it("renders a responsive bottom chat composer with textarea and send state", async () => {
    const wrapper = mount(HomeView)
    const textarea = wrapper.get('[data-testid="chat-input"]')
    const sendButton = wrapper.get('[data-testid="send-button"]')
    const composer = wrapper.get('[data-testid="chat-composer"]')

    expect(composer.classes()).toContain("fixed")
    expect(composer.classes()).toContain("bottom-0")
    expect(textarea.attributes("placeholder")).toBe("请输入你的问题...")
    expect(sendButton.attributes()).toHaveProperty("disabled")
    expect(sendButton.classes()).toContain("bg-zinc-200")

    const element = textarea.element as HTMLTextAreaElement
    Object.defineProperty(element, "scrollHeight", {
      configurable: true,
      value: 96,
    })

    await textarea.setValue("请总结我的课程笔记")

    expect(sendButton.attributes("disabled")).toBeUndefined()
    expect(sendButton.classes()).toContain("bg-zinc-950")
    expect(element.style.height).toBe("96px")
  })

  it("opens the file picker from the attachment button and lets users remove the selected file", async () => {
    const wrapper = mount(HomeView)
    const attachmentButton = wrapper.get('[data-testid="attachment-button"]')
    const fileInput = wrapper.get('[data-testid="attachment-input"]')
    const inputElement = fileInput.element as HTMLInputElement
    const clickSpy = vi.spyOn(inputElement, "click").mockImplementation(() => {})

    await attachmentButton.trigger("click")

    expect(clickSpy).toHaveBeenCalledOnce()

    const file = new File(["notes"], "course-notes.pdf", {
      type: "application/pdf",
    })
    Object.defineProperty(inputElement, "files", {
      configurable: true,
      value: [file],
    })

    await fileInput.trigger("change")

    expect(wrapper.get('[data-testid="selected-file-chip"]').text()).toContain(
      "course-notes.pdf",
    )

    await wrapper.get('[data-testid="remove-attachment-button"]').trigger("click")

    expect(wrapper.find('[data-testid="selected-file-chip"]').exists()).toBe(false)
    expect(inputElement.value).toBe("")
  })

  it("sends with Enter and keeps content for Shift+Enter", async () => {
    const wrapper = mount(HomeView)
    const textarea = wrapper.get('[data-testid="chat-input"]')

    await textarea.setValue("Summarize my notes")
    await textarea.trigger("keydown", { key: "Enter" })

    expect((textarea.element as HTMLTextAreaElement).value).toBe("")

    await textarea.setValue("First line")
    await textarea.trigger("keydown", { key: "Enter", shiftKey: true })

    expect((textarea.element as HTMLTextAreaElement).value).toBe("First line")
  })
})
