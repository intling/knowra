import { mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import { beforeEach, describe, expect, it, vi } from "vitest"

import HomeView from "./HomeView.vue"

const mocks = vi.hoisted(() => ({
  refreshHealthMock: vi.fn(),
  loadCurrentUserMock: vi.fn(),
  uploadFileMock: vi.fn(),
  userStoreState: {
    currentUser: {
      display_name: "Default User",
    } as { display_name: string } | null,
    isUserLoading: false,
    userError: null as string | null,
  },
}))

vi.mock("../stores/app", () => ({
  useAppStore: () => ({
    health: {
      status: "ok",
      environment: "local",
    },
    isHealthLoading: false,
    healthError: null,
    lastHealthCheckedAt: null,
    refreshHealth: mocks.refreshHealthMock,
  }),
}))

vi.mock("../stores/user", () => ({
  useUserStore: () => ({
    currentUser: mocks.userStoreState.currentUser,
    isUserLoading: mocks.userStoreState.isUserLoading,
    userError: mocks.userStoreState.userError,
    loadCurrentUser: mocks.loadCurrentUserMock,
  }),
}))

vi.mock("../api/uploads", () => ({
  uploadFile: mocks.uploadFileMock,
}))

describe("HomeView", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mocks.refreshHealthMock.mockReset()
    mocks.loadCurrentUserMock.mockReset()
    mocks.uploadFileMock.mockReset()
    mocks.userStoreState.currentUser = {
      display_name: "Default User",
    }
    mocks.userStoreState.isUserLoading = false
    mocks.userStoreState.userError = null
  })

  it("shows current user context without authentication actions", () => {
    const wrapper = mount(HomeView)
    const text = wrapper.text()

    expect(text).toContain("Default User")
    expect(text).not.toContain("\u767b\u5f55")
    expect(text).not.toContain("\u6ce8\u518c")
    expect(text).not.toContain("\u9000\u51fa")
    expect(text).not.toContain("\u5207\u6362\u7528\u6237")
    expect(mocks.loadCurrentUserMock).toHaveBeenCalledOnce()
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

  it("uploads the selected file, clears it after success, and shows success feedback", async () => {
    mocks.uploadFileMock.mockResolvedValue({
      original_filename: "course-notes.pdf",
    })
    const wrapper = mount(HomeView)
    const fileInput = wrapper.get('[data-testid="attachment-input"]')
    const inputElement = fileInput.element as HTMLInputElement
    const file = new File(["notes"], "course-notes.pdf", {
      type: "application/pdf",
    })
    Object.defineProperty(inputElement, "files", {
      configurable: true,
      value: [file],
    })

    await fileInput.trigger("change")
    await wrapper.get('[data-testid="send-button"]').trigger("submit")

    expect(mocks.uploadFileMock).toHaveBeenCalledWith(file)
    expect(wrapper.find('[data-testid="selected-file-chip"]').exists()).toBe(false)
    expect(inputElement.value).toBe("")
    expect(wrapper.get('[data-testid="upload-status"]').text()).toContain(
      "course-notes.pdf 上传成功",
    )
  })

  it("disables duplicate submit while upload is in progress", async () => {
    let resolveUpload: (value: unknown) => void = () => {}
    mocks.uploadFileMock.mockReturnValue(
      new Promise((resolve) => {
        resolveUpload = resolve
      }),
    )
    const wrapper = mount(HomeView)
    const fileInput = wrapper.get('[data-testid="attachment-input"]')
    const inputElement = fileInput.element as HTMLInputElement
    const file = new File(["notes"], "course-notes.pdf", {
      type: "application/pdf",
    })
    Object.defineProperty(inputElement, "files", {
      configurable: true,
      value: [file],
    })

    await fileInput.trigger("change")
    await wrapper.get("form").trigger("submit")
    await wrapper.get("form").trigger("submit")

    expect(mocks.uploadFileMock).toHaveBeenCalledOnce()
    expect(wrapper.get('[data-testid="send-button"]').attributes()).toHaveProperty(
      "disabled",
    )
    expect(wrapper.get('[data-testid="upload-status"]').text()).toContain("上传中")

    resolveUpload({ original_filename: "course-notes.pdf" })
    await Promise.resolve()
  })

  it("keeps the selected file and shows an error when upload fails", async () => {
    mocks.uploadFileMock.mockRejectedValue(new Error("File size exceeds max_upload_bytes"))
    const wrapper = mount(HomeView)
    const fileInput = wrapper.get('[data-testid="attachment-input"]')
    const inputElement = fileInput.element as HTMLInputElement
    const file = new File(["notes"], "course-notes.pdf", {
      type: "application/pdf",
    })
    Object.defineProperty(inputElement, "files", {
      configurable: true,
      value: [file],
    })

    await fileInput.trigger("change")
    await wrapper.get("form").trigger("submit")
    await Promise.resolve()

    expect(wrapper.get('[data-testid="selected-file-chip"]').text()).toContain(
      "course-notes.pdf",
    )
    expect(wrapper.get('[data-testid="upload-status"]').text()).toContain(
      "File size exceeds max_upload_bytes",
    )
  })

  it("disables upload submit when the current user is unavailable", async () => {
    mocks.userStoreState.currentUser = null
    mocks.userStoreState.isUserLoading = false
    mocks.userStoreState.userError = "Current user is unavailable"
    const wrapper = mount(HomeView)
    const fileInput = wrapper.get('[data-testid="attachment-input"]')
    const inputElement = fileInput.element as HTMLInputElement
    Object.defineProperty(inputElement, "files", {
      configurable: true,
      value: [
        new File(["notes"], "course-notes.pdf", {
          type: "application/pdf",
        }),
      ],
    })

    await fileInput.trigger("change")
    await wrapper.get("form").trigger("submit")

    expect(mocks.uploadFileMock).not.toHaveBeenCalled()
    expect(wrapper.get('[data-testid="send-button"]').attributes()).toHaveProperty(
      "disabled",
    )
    expect(wrapper.get('[data-testid="upload-status"]').text()).toContain(
      "当前用户不可用",
    )
  })

  it("does not upload a selected file when user is unavailable even with text input", async () => {
    mocks.userStoreState.currentUser = null
    mocks.userStoreState.isUserLoading = false
    mocks.userStoreState.userError = "Current user is unavailable"
    const wrapper = mount(HomeView)
    const fileInput = wrapper.get('[data-testid="attachment-input"]')
    const inputElement = fileInput.element as HTMLInputElement
    Object.defineProperty(inputElement, "files", {
      configurable: true,
      value: [
        new File(["notes"], "course-notes.pdf", {
          type: "application/pdf",
        }),
      ],
    })

    await fileInput.trigger("change")
    await wrapper.get('[data-testid="chat-input"]').setValue("总结这份资料")
    await wrapper.get("form").trigger("submit")

    expect(mocks.uploadFileMock).not.toHaveBeenCalled()
    expect(wrapper.get('[data-testid="selected-file-chip"]').text()).toContain(
      "course-notes.pdf",
    )
    expect(wrapper.get('[data-testid="upload-status"]').text()).toContain(
      "当前用户不可用",
    )
  })
})
