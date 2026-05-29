import { flushPromises, mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import { beforeEach, describe, expect, it, vi } from "vitest"

import HomeView from "./HomeView.vue"

// 本文件验证首页用户上下文、聊天输入、附件上传和资料列表的关键交互。

const mocks = vi.hoisted(() => ({
  refreshHealthMock: vi.fn(),
  loadCurrentUserMock: vi.fn(),
  uploadFileMock: vi.fn(),
  listDocumentsMock: vi.fn(),
  createDocumentMock: vi.fn(),
  DocumentConflictErrorMock: class DocumentConflictError extends Error {
    constructor(readonly existingDocument: unknown) {
      super("Document already exists")
      this.name = "DocumentConflictError"
    }
  },
  userStoreState: {
    currentUser: {
      id: "user-1",
      display_name: "Default User",
      email: "default@example.com",
      avatar_url: null,
      status: "active",
      deleted_at: null,
      created_at: "2026-05-20T09:00:00Z",
      updated_at: "2026-05-20T09:00:00Z",
    } as {
      id: string
      display_name: string
      email: string | null
      avatar_url: string | null
      status: string
      deleted_at: string | null
      created_at: string
      updated_at: string
    } | null,
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

vi.mock("../api/documents", () => ({
  listDocuments: mocks.listDocumentsMock,
  createDocument: mocks.createDocumentMock,
  DocumentConflictError: mocks.DocumentConflictErrorMock,
}))

const buildDocument = (overrides: Record<string, unknown> = {}) => ({
  id: "parsed-doc",
  owner_user_id: "user-1",
  uploaded_file_id: "upload-1",
  title: "course-notes.pdf",
  source_content_type: "application/pdf",
  parser_name: "pdf",
  parser_version: "1",
  chunker_name: "bpe-window",
  chunker_version: "1",
  tokenizer_name: "cl100k_base",
  tokenizer_version: "1",
  status: "parsed",
  chunk_count: 3,
  total_chars: 1200,
  content_sha256: "hash",
  metadata_json: {},
  error_message: null,
  deleted_at: null,
  created_at: "2026-05-28T09:00:00Z",
  updated_at: "2026-05-28T09:00:00Z",
  source_file: {
    id: "upload-1",
    original_filename: "course-notes.pdf",
    content_type: "application/pdf",
    byte_size: 204800,
    status: "stored",
  },
  ...overrides,
})

describe("HomeView", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mocks.refreshHealthMock.mockReset()
    mocks.loadCurrentUserMock.mockReset()
    mocks.uploadFileMock.mockReset()
    mocks.listDocumentsMock.mockReset()
    mocks.createDocumentMock.mockReset()
    mocks.listDocumentsMock.mockResolvedValue([])
    mocks.createDocumentMock.mockResolvedValue({
      id: "processed-doc",
      title: "course-notes.pdf",
      status: "parsed",
      chunk_count: 1,
    })
    mocks.userStoreState.currentUser = {
      id: "user-1",
      display_name: "Default User",
      email: "default@example.com",
      avatar_url: null,
      status: "active",
      deleted_at: null,
      created_at: "2026-05-20T09:00:00Z",
      updated_at: "2026-05-20T09:00:00Z",
    }
    mocks.userStoreState.isUserLoading = false
    mocks.userStoreState.userError = null
  })

  // 测试：首页使用类 ChatGPT 的全高布局，用户头像固定在侧栏底部，点击后在头像上方打开账户抽屉。
  it("opens an account drawer above the sidebar user avatar", async () => {
    const wrapper = mount(HomeView)

    expect(wrapper.get('[data-testid="home-shell"]').classes()).toContain(
      "h-screen",
    )
    expect(
      wrapper.get('[data-testid="sidebar-user-area"]').classes(),
    ).toContain("mt-auto")
    await wrapper.get('[data-testid="user-avatar-button"]').trigger("click")

    const drawer = wrapper.get('[data-testid="account-drawer"]')
    expect(drawer.classes()).toContain("absolute")
    expect(drawer.classes()).toContain("bottom-14")
    expect(drawer.classes()).not.toContain("fixed")
    expect(drawer.classes()).not.toContain("right-0")
    expect(drawer.text()).toContain("设置")
    expect(drawer.text()).toContain("个人知识库")
    expect(drawer.text()).toContain("退出登录")
    expect(drawer.text()).toContain("Default User")
    expect(wrapper.text()).not.toContain("\u6ce8\u518c")
    expect(wrapper.text()).not.toContain("\u5207\u6362\u7528\u6237")
    expect(mocks.loadCurrentUserMock).toHaveBeenCalledOnce()
  })

  // 测试：从账户抽屉点击设置时，会打开悬浮模态框并展示当前用户的基础资料。
  it("opens a floating settings modal with current user profile details", async () => {
    const wrapper = mount(HomeView)

    await wrapper.get('[data-testid="user-avatar-button"]').trigger("click")
    await wrapper.get('[data-testid="settings-menu-item"]').trigger("click")

    const modal = wrapper.get('[data-testid="settings-modal"]')
    expect(modal.text()).toContain("个人信息")
    expect(modal.text()).toContain("Default User")
    expect(modal.text()).toContain("default@example.com")
    expect(modal.text()).toContain("active")

    await wrapper.get('[data-testid="settings-modal-close"]').trigger("click")

    expect(wrapper.find('[data-testid="settings-modal"]').exists()).toBe(false)
  })

  // 测试：点击个人知识库会进入资料库管理界面，顶部包含搜索与上传按钮，下方以分类标签和四列表格展示资源。
  it("shows the personal knowledge library toolbar, filters, and resource table", async () => {
    mocks.listDocumentsMock.mockResolvedValue([
      buildDocument({
        title: "agments.txt",
        source_content_type: "text/plain",
        updated_at: "2026-05-28T09:30:00Z",
        source_file: {
          id: "upload-1",
          original_filename: "agments.txt",
          content_type: "text/plain",
          byte_size: 4946,
          status: "stored",
        },
      }),
      buildDocument({
        id: "image-doc",
        uploaded_file_id: "upload-2",
        title: "diagram.png",
        source_content_type: "image/png",
        source_file: {
          id: "upload-2",
          original_filename: "diagram.png",
          content_type: "image/png",
          byte_size: 4096,
          status: "stored",
        },
      }),
    ])
    const wrapper = mount(HomeView)
    await flushPromises()

    await wrapper.get('[data-testid="user-avatar-button"]').trigger("click")
    await wrapper
      .get('[data-testid="knowledge-library-menu-item"]')
      .trigger("click")

    const library = wrapper.get('[data-testid="knowledge-library-view"]')
    expect(library.text()).toContain("个人知识库")
    expect(library.classes()).toContain("grid")

    const toolbar = wrapper.get('[data-testid="knowledge-library-toolbar"]')
    expect(
      wrapper.get('[data-testid="library-search-input"]').attributes(
        "placeholder",
      ),
    ).toBe("搜索资料库")
    expect(toolbar.text()).toContain("上传")
    expect(
      wrapper.get('[data-testid="library-upload-button"]').attributes(
        "aria-label",
      ),
    ).toBe("上传资料")
    expect(
      wrapper.find('[data-testid="library-create-menu"]').exists(),
    ).toBe(false)

    const filters = wrapper.get('[data-testid="library-filter-tabs"]')
    expect(filters.text()).toContain("全部")
    expect(filters.text()).toContain("图片")
    expect(filters.text()).toContain("文件")
    expect(wrapper.get('[data-testid="library-filter-all"]').classes()).toContain(
      "bg-zinc-100",
    )

    const header = wrapper.get('[data-testid="library-table-header"]')
    expect(header.text()).toContain("名称")
    expect(header.text()).toContain("已修改 ↓")
    expect(header.text()).toContain("大小")
    expect(header.text()).toContain("操作")

    const pdfRow = wrapper.get('[data-testid="library-file-row-parsed-doc"]')
    expect(
      wrapper
        .get('[data-testid="library-file-select-parsed-doc"]')
        .classes(),
    ).toContain("rounded-md")
    expect(pdfRow.text()).toContain("TXT")
    expect(pdfRow.text()).toContain("agments.txt")
    expect(pdfRow.text()).toContain("4.83 KB")
    expect(pdfRow.text()).toContain("已解析")
    expect(
      wrapper
        .get('[data-testid="library-file-download-parsed-doc"]')
        .attributes("aria-label"),
    ).toContain("下载 agments.txt")
    expect(
      wrapper
        .get('[data-testid="library-file-delete-parsed-doc"]')
        .attributes("aria-label"),
    ).toContain("删除 agments.txt")
    expect(
      wrapper.get('[data-testid="library-file-row-image-doc"]').text(),
    ).toContain("IMG")
  })

  // 测试：资料库表格最左侧提供圆角矩形复选框，用户可勾选当前文件。
  it("selects a knowledge library file from the leftmost rounded checkbox", async () => {
    mocks.listDocumentsMock.mockResolvedValue([buildDocument()])
    const wrapper = mount(HomeView)
    await flushPromises()

    await wrapper.get('[data-testid="user-avatar-button"]').trigger("click")
    await wrapper
      .get('[data-testid="knowledge-library-menu-item"]')
      .trigger("click")

    const checkbox = wrapper.get('[data-testid="library-file-select-parsed-doc"]')

    expect(checkbox.attributes("type")).toBe("checkbox")
    expect(checkbox.classes()).toContain("size-4")
    expect(checkbox.classes()).toContain("rounded-md")
    expect((checkbox.element as HTMLInputElement).checked).toBe(false)

    const row = wrapper.get('[data-testid="library-file-row-parsed-doc"]')
    expect(row.classes()).toContain("hover:bg-zinc-100")
    expect(row.classes()).toContain("bg-white")
    expect(
      wrapper.find('[data-testid="library-file-check-parsed-doc"]').exists(),
    ).toBe(false)

    await checkbox.setValue(true)

    expect((checkbox.element as HTMLInputElement).checked).toBe(true)
    expect(row.classes()).toContain("bg-zinc-100")
    expect(
      wrapper.get('[data-testid="library-file-check-parsed-doc"]').classes(),
    ).toContain("text-white")

    await checkbox.setValue(false)

    expect((checkbox.element as HTMLInputElement).checked).toBe(false)
    expect(row.classes()).toContain("bg-white")
    expect(row.classes()).not.toContain("bg-zinc-100")
    expect(
      wrapper.find('[data-testid="library-file-check-parsed-doc"]').exists(),
    ).toBe(false)
  })

  // 测试：资料库支持按资源类型标签筛选，并支持通过搜索框快速缩小结果。
  it("filters knowledge library resources by category and search keyword", async () => {
    mocks.listDocumentsMock.mockResolvedValue([
      buildDocument({
        title: "agments.txt",
        source_content_type: "text/plain",
        source_file: {
          id: "upload-1",
          original_filename: "agments.txt",
          content_type: "text/plain",
          byte_size: 4946,
          status: "stored",
        },
      }),
      buildDocument({
        id: "image-doc",
        uploaded_file_id: "upload-2",
        title: "diagram.png",
        source_content_type: "image/png",
        source_file: {
          id: "upload-2",
          original_filename: "diagram.png",
          content_type: "image/png",
          byte_size: 4096,
          status: "stored",
        },
      }),
    ])
    const wrapper = mount(HomeView)
    await flushPromises()

    await wrapper.get('[data-testid="user-avatar-button"]').trigger("click")
    await wrapper
      .get('[data-testid="knowledge-library-menu-item"]')
      .trigger("click")

    await wrapper.get('[data-testid="library-filter-image"]').trigger("click")

    expect(
      wrapper.find('[data-testid="library-file-row-parsed-doc"]').exists(),
    ).toBe(false)
    expect(
      wrapper.find('[data-testid="library-file-row-image-doc"]').exists(),
    ).toBe(true)

    await wrapper.get('[data-testid="library-filter-file"]').trigger("click")

    expect(
      wrapper.find('[data-testid="library-file-row-parsed-doc"]').exists(),
    ).toBe(true)
    expect(
      wrapper.find('[data-testid="library-file-row-image-doc"]').exists(),
    ).toBe(false)

    await wrapper.get('[data-testid="library-filter-all"]').trigger("click")
    await wrapper.get('[data-testid="library-search-input"]').setValue("diagram")

    expect(
      wrapper.find('[data-testid="library-file-row-parsed-doc"]').exists(),
    ).toBe(false)
    expect(
      wrapper.find('[data-testid="library-file-row-image-doc"]').exists(),
    ).toBe(true)
  })

  // 测试：点击退出登录后，会清空左侧最近对话和个人知识库列表，并把界面切换为未登录状态。
  it("logs out locally and clears recent conversations and the knowledge library", async () => {
    mocks.listDocumentsMock.mockResolvedValue([buildDocument()])
    const wrapper = mount(HomeView)
    await flushPromises()

    await wrapper.get('[data-testid="user-avatar-button"]').trigger("click")
    await wrapper
      .get('[data-testid="knowledge-library-menu-item"]')
      .trigger("click")
    expect(
      wrapper.get('[data-testid="recent-conversations"]').text(),
    ).toContain("课程资料问答")
    expect(
      wrapper.find('[data-testid="library-file-row-parsed-doc"]').exists(),
    ).toBe(true)

    await wrapper.get('[data-testid="user-avatar-button"]').trigger("click")
    await wrapper.get('[data-testid="logout-menu-item"]').trigger("click")

    expect(
      wrapper.get('[data-testid="recent-conversations"]').text(),
    ).toContain("暂无最近对话")
    expect(
      wrapper.get('[data-testid="knowledge-empty-state"]').text(),
    ).toContain("个人知识库为空")
    expect(
      wrapper.find('[data-testid="library-file-row-parsed-doc"]').exists(),
    ).toBe(false)
    expect(wrapper.get('[data-testid="user-avatar-button"]').text()).toContain(
      "未",
    )
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
    const clickSpy = vi
      .spyOn(inputElement, "click")
      .mockImplementation(() => {})

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

    await wrapper
      .get('[data-testid="remove-attachment-button"]')
      .trigger("click")

    expect(wrapper.find('[data-testid="selected-file-chip"]').exists()).toBe(
      false,
    )
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

  // 测试：文件上传成功后会调用上传接口、清空已选文件，并展示成功反馈。
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
    expect(wrapper.find('[data-testid="selected-file-chip"]').exists()).toBe(
      false,
    )
    expect(inputElement.value).toBe("")
    expect(wrapper.get('[data-testid="upload-status"]').text()).toContain(
      "course-notes.pdf 上传成功",
    )
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
    expect(
      wrapper.get('[data-testid="send-button"]').attributes(),
    ).toHaveProperty("disabled")
    expect(wrapper.get('[data-testid="upload-status"]').text()).toContain(
      "上传中",
    )

    resolveUpload({ original_filename: "course-notes.pdf" })
    await Promise.resolve()
  })

  // 测试：上传失败时会保留已选文件，并在界面上展示错误信息。
  it("keeps the selected file and shows an error when upload fails", async () => {
    mocks.uploadFileMock.mockRejectedValue(
      new Error("File size exceeds max_upload_bytes"),
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
    expect(
      wrapper.get('[data-testid="send-button"]').attributes(),
    ).toHaveProperty("disabled")
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

  // 测试：资料列表会展示 parsed 和 failed 文档，failed 文档包含失败原因和重试入口。
  it("shows parsed and failed documents with failure reasons and retry action", async () => {
    mocks.listDocumentsMock.mockResolvedValue([
      {
        id: "parsed-doc",
        uploaded_file_id: "upload-1",
        title: "course-notes.pdf",
        status: "parsed",
        chunk_count: 3,
        error_message: null,
        created_at: "2026-05-28T09:00:00Z",
        source_file: {
          original_filename: "course-notes.pdf",
        },
      },
      {
        id: "failed-doc",
        uploaded_file_id: "upload-2",
        title: "scan.pdf",
        status: "failed",
        chunk_count: 0,
        error_message: "PDF 缺少可抽取文本，需要 OCR",
        created_at: "2026-05-28T09:10:00Z",
        source_file: {
          original_filename: "scan.pdf",
        },
      },
    ])

    const wrapper = mount(HomeView)
    await flushPromises()

    expect(mocks.listDocumentsMock).toHaveBeenCalledOnce()
    await wrapper.get('[data-testid="user-avatar-button"]').trigger("click")
    await wrapper
      .get('[data-testid="knowledge-library-menu-item"]')
      .trigger("click")

    const list = wrapper.get('[data-testid="document-list"]')
    expect(list.text()).toContain("course-notes.pdf")
    expect(list.text()).toContain("已解析")
    expect(list.text()).toContain("3 个片段")
    expect(list.text()).toContain("scan.pdf")
    expect(list.text()).toContain("解析失败")
    expect(list.text()).toContain("PDF 缺少可抽取文本，需要 OCR")
    expect(
      wrapper.get('[data-testid="retry-document-button"]').text(),
    ).toContain("重试")
  })

  // 测试：上传后文档处理遇到 409 existing_document 时，会展示已有文档信息而不是普通上传成功。
  it("shows existing document feedback when document processing returns a conflict", async () => {
    mocks.uploadFileMock.mockResolvedValue({
      id: "upload-1",
      original_filename: "course-notes.pdf",
    })
    mocks.createDocumentMock.mockRejectedValue(
      new mocks.DocumentConflictErrorMock({
        id: "existing-doc",
        title: "course-notes.pdf",
        status: "parsed",
        chunk_count: 4,
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
    await flushPromises()

    expect(mocks.uploadFileMock).toHaveBeenCalledWith(file)
    expect(mocks.createDocumentMock).toHaveBeenCalledWith("upload-1")
    expect(wrapper.get('[data-testid="upload-status"]').text()).toContain(
      "course-notes.pdf 已处理",
    )
    expect(wrapper.get('[data-testid="upload-status"]').text()).toContain(
      "4 个片段",
    )
  })
})
