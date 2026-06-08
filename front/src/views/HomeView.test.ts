import { flushPromises, mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import { beforeEach, describe, expect, it, vi } from "vitest"

import HomeView from "./HomeView.vue"

const mocks = vi.hoisted(() => ({
  refreshHealthMock: vi.fn(),
  loadCurrentUserMock: vi.fn(),
  uploadFileMock: vi.fn(),
  createDocumentParseJobMock: vi.fn(),
  getDocumentParseJobMock: vi.fn(),
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

vi.mock("../api/documentParsing", () => ({
  createDocumentParseJob: mocks.createDocumentParseJobMock,
  getDocumentParseJob: mocks.getDocumentParseJobMock,
}))

describe("HomeView", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mocks.refreshHealthMock.mockReset()
    mocks.loadCurrentUserMock.mockReset()
    mocks.uploadFileMock.mockReset()
    mocks.createDocumentParseJobMock.mockReset()
    mocks.getDocumentParseJobMock.mockReset()
    mocks.createDocumentParseJobMock.mockResolvedValue({
      id: "22222222-2222-2222-2222-222222222222",
      uploaded_file_id: "11111111-1111-1111-1111-111111111111",
      status: "queued",
      parser_name: "docling",
      parser_version: null,
      error_code: null,
      error_message: null,
      created_at: "2026-06-08T00:00:00Z",
      started_at: null,
      finished_at: null,
    })
    mocks.getDocumentParseJobMock.mockResolvedValue({
      id: "22222222-2222-2222-2222-222222222222",
      uploaded_file_id: "11111111-1111-1111-1111-111111111111",
      status: "succeeded",
      parser_name: "docling",
      parser_version: null,
      error_code: null,
      error_message: null,
      created_at: "2026-06-08T00:00:00Z",
      started_at: "2026-06-08T00:00:01Z",
      finished_at: "2026-06-08T00:00:02Z",
    })
    mocks.userStoreState.currentUser = {
      display_name: "Default User",
    }
    mocks.userStoreState.isUserLoading = false
    mocks.userStoreState.userError = null
  })

  // 测试：首页会展示当前用户上下文，并且不显示登录、注册、退出或切换用户等认证操作。
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

  // 测试：底部聊天输入区固定在底部，输入内容后发送按钮状态和文本框高度会正确更新。
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

  // 测试：附件按钮会打开文件选择器，选择文件后展示文件标签，并支持移除已选文件。
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

  // 测试：按 Enter 会发送并清空输入，按 Shift+Enter 会保留内容用于换行输入。
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

  // 测试：文件上传成功后会调用上传接口、清空已选文件、展示成功反馈，并自动提交解析作业。
  it("uploads the selected file, clears it after success, shows success feedback, and auto-starts parsing", async () => {
    mocks.uploadFileMock.mockResolvedValue({
      id: "11111111-1111-1111-1111-111111111111",
      original_filename: "course-notes.pdf",
      content_type: "application/pdf",
      byte_size: 5,
      status: "stored",
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
    await wrapper.get("form").trigger("submit")
    await flushPromises()

    expect(mocks.uploadFileMock).toHaveBeenCalledWith(file)
    expect(mocks.createDocumentParseJobMock).toHaveBeenCalledWith(
      "11111111-1111-1111-1111-111111111111",
    )
    expect(mocks.getDocumentParseJobMock).toHaveBeenCalledWith(
      "22222222-2222-2222-2222-222222222222",
    )
    expect(wrapper.find('[data-testid="selected-file-chip"]').exists()).toBe(false)
    expect(inputElement.value).toBe("")
    expect(wrapper.get('[data-testid="upload-status"]').text()).toContain(
      "course-notes.pdf 上传成功",
    )
  })

  // 测试：上传成功后会自动进入解析流程，不需要用户点击解析按钮。
  it("automatically starts parsing after a file upload succeeds", async () => {
    mocks.uploadFileMock.mockResolvedValue({
      id: "11111111-1111-1111-1111-111111111111",
      original_filename: "course-notes.pdf",
      content_type: "application/pdf",
      byte_size: 5,
      status: "stored",
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
    await wrapper.get("form").trigger("submit")
    await flushPromises()

    expect(mocks.createDocumentParseJobMock).toHaveBeenCalledWith(
      "11111111-1111-1111-1111-111111111111",
    )
    expect(mocks.getDocumentParseJobMock).toHaveBeenCalledWith(
      "22222222-2222-2222-2222-222222222222",
    )
    expect(wrapper.find('[data-testid="parse-action-button"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="parse-status"]').text()).toContain(
      "解析成功",
    )
  })

  // 测试：解析作业只有真正 succeeded 后才展示解析成功。
  it("shows parse success only after the parse job succeeds", async () => {
    mocks.uploadFileMock.mockResolvedValue({
      id: "11111111-1111-1111-1111-111111111111",
      original_filename: "course-notes.pdf",
      content_type: "application/pdf",
      byte_size: 5,
      status: "stored",
    })
    mocks.createDocumentParseJobMock.mockResolvedValue({
      id: "22222222-2222-2222-2222-222222222222",
      uploaded_file_id: "11111111-1111-1111-1111-111111111111",
      status: "queued",
    })
    mocks.getDocumentParseJobMock.mockResolvedValue({
      id: "22222222-2222-2222-2222-222222222222",
      uploaded_file_id: "11111111-1111-1111-1111-111111111111",
      status: "succeeded",
    })
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
    await flushPromises()

    expect(wrapper.get('[data-testid="parse-status"]').text()).toContain(
      "解析成功",
    )
    expect(wrapper.get('[data-testid="parse-status"]').text()).not.toContain(
      "解析已提交",
    )
  })

  // 测试：解析作业失败时展示失败原因并允许重试，而不是显示已提交。
  it("shows parse failure and retry when the parse job fails", async () => {
    mocks.uploadFileMock.mockResolvedValue({
      id: "11111111-1111-1111-1111-111111111111",
      original_filename: "blank.pdf",
      content_type: "application/pdf",
      byte_size: 5,
      status: "stored",
    })
    mocks.getDocumentParseJobMock.mockResolvedValue({
      id: "22222222-2222-2222-2222-222222222222",
      uploaded_file_id: "11111111-1111-1111-1111-111111111111",
      status: "failed",
      error_message: "Parsed document has no text content",
    })
    const wrapper = mount(HomeView)
    const fileInput = wrapper.get('[data-testid="attachment-input"]')
    const inputElement = fileInput.element as HTMLInputElement
    Object.defineProperty(inputElement, "files", {
      configurable: true,
      value: [
        new File([""], "blank.pdf", {
          type: "application/pdf",
        }),
      ],
    })

    await fileInput.trigger("change")
    await wrapper.get("form").trigger("submit")
    await flushPromises()

    expect(wrapper.get('[data-testid="parse-status"]').text()).toContain(
      "Parsed document has no text content",
    )
    expect(wrapper.get('[data-testid="parse-status"]').text()).not.toContain(
      "解析已提交",
    )
    expect(wrapper.find('[data-testid="parse-action-button"]').exists()).toBe(true)
  })

  // 测试：文件选择器 accept 反映当前上传入口支持范围，包含 PPTX 格式。
  it("keeps upload accept formats consistent with upload and parse supported types", () => {
    const wrapper = mount(HomeView)
    const accept = wrapper.get('[data-testid="attachment-input"]').attributes("accept")

    expect(accept).toBe(
      ".pdf,.md,.markdown,.txt,.docx,.pptx,application/pdf,text/markdown,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
    expect(accept).toContain(".pptx")
    expect(accept).toContain("presentationml")
  })

  // 测试：自动解析提交中不会展示手动解析按钮，并展示解析中状态。
  it("does not show a manual parse trigger while the automatic parse job is being submitted", async () => {
    let resolveParse!: (value: unknown) => void
    mocks.uploadFileMock.mockResolvedValue({
      id: "11111111-1111-1111-1111-111111111111",
      original_filename: "course-notes.pdf",
      content_type: "application/pdf",
      byte_size: 5,
      status: "stored",
    })
    mocks.createDocumentParseJobMock.mockReturnValue(
      new Promise((resolve) => {
        resolveParse = resolve
      }),
    )
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
    await Promise.resolve()

    expect(mocks.createDocumentParseJobMock).toHaveBeenCalledOnce()
    expect(wrapper.find('[data-testid="parse-action-button"]').exists()).toBe(
      false,
    )
    expect(wrapper.get('[data-testid="parse-status"]').text()).toContain(
      "解析中",
    )

    resolveParse({ id: "job-1", status: "queued" })
    await Promise.resolve()
  })

  // 测试：上传进行中会禁用提交，避免重复触发上传请求，并展示上传中状态。
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

  // 测试：上传失败时会保留已选文件，并在界面上展示错误信息。
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

  // 测试：当前用户不可用时，即使选择了文件也不会提交上传，并会禁用发送按钮。
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

  // 测试：当前用户不可用时，即使同时存在文本输入和已选文件，也不会发起上传请求。
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
