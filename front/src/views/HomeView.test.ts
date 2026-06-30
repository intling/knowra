import { flushPromises, mount, type VueWrapper } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import { beforeEach, describe, expect, it, vi } from "vitest"

import HomeView from "./HomeView.vue"

vi.mock("../shared/logger", () => ({
  createLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
  getRingBuffer: () => ({ push: vi.fn(), size: 0, getAll: () => [] }),
}))

const mocks = vi.hoisted(() => ({
  refreshHealthMock: vi.fn(),
  loadCurrentUserMock: vi.fn(),
  uploadFileMock: vi.fn(),
  createDocumentParseJobMock: vi.fn(),
  getDocumentParseJobMock: vi.fn(),
  getParsedDocumentForUploadMock: vi.fn(),
  getDocumentChunkJobMock: vi.fn(),
  getLatestParsedDocumentChunkJobMock: vi.fn(),
  getParsedDocumentChunksMock: vi.fn(),
  getDocumentChunkMock: vi.fn(),
  rechunkParsedDocumentMock: vi.fn(),
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
  getParsedDocumentForUpload: mocks.getParsedDocumentForUploadMock,
}))

vi.mock("../api/documentChunking", () => ({
  getDocumentChunkJob: mocks.getDocumentChunkJobMock,
  getLatestParsedDocumentChunkJob: mocks.getLatestParsedDocumentChunkJobMock,
  getParsedDocumentChunks: mocks.getParsedDocumentChunksMock,
  getDocumentChunk: mocks.getDocumentChunkMock,
  rechunkParsedDocument: mocks.rechunkParsedDocumentMock,
}))

const UPLOADED_FILE_RESPONSE = {
  id: "11111111-1111-1111-1111-111111111111",
  owner_user_id: "00000000-0000-0000-0000-000000000001",
  original_filename: "course-notes.pdf",
  content_type: "application/pdf",
  byte_size: 5,
  storage_key: "uploads/default/course-notes.pdf",
  checksum_sha256: "a".repeat(64),
  status: "stored",
  error_message: null,
  deleted_at: null,
  created_at: "2026-06-12T00:00:00Z",
  updated_at: "2026-06-12T00:00:00Z",
}

const PARSED_DOCUMENT_RESPONSE = {
  id: "33333333-3333-3333-3333-333333333333",
  uploaded_file_id: UPLOADED_FILE_RESPONSE.id,
  parse_job_id: "22222222-2222-2222-2222-222222222222",
  owner_user_id: "00000000-0000-0000-0000-000000000001",
  source_checksum_sha256: "a".repeat(64),
  markdown_storage_key: "parsed/u/f/j/content.md",
  text_storage_key: "parsed/u/f/j/content.txt",
  docling_json_storage_key: "parsed/u/f/j/docling.json",
  title: "Course Notes",
  page_count: 2,
  metadata: { parser: "docling" },
  segment_count: 2,
  created_at: "2026-06-12T00:00:01Z",
}

const CHUNK_JOB_RESPONSE = {
  id: "55555555-5555-5555-5555-555555555555",
  parsed_document_id: PARSED_DOCUMENT_RESPONSE.id,
  owner_user_id: "00000000-0000-0000-0000-000000000001",
  status: "succeeded",
  chunker_name: "docling_hybrid",
  chunker_version: "docling-core",
  chunk_config_json: {
    max_tokens: 512,
    tokenizer_model: "Qwen/Qwen2-7B",
    merge_peers: true,
    repeat_table_header: true,
    inline_text_max_bytes: 2048,
  },
  chunk_count: 2,
  attempt_count: 1,
  started_at: "2026-06-12T00:00:02Z",
  finished_at: "2026-06-12T00:00:03Z",
  error_code: null,
  error_message: null,
  created_at: "2026-06-12T00:00:02Z",
  updated_at: "2026-06-12T00:00:03Z",
}

const CHUNK_PAGE_RESPONSE = {
  items: [
    {
      id: "66666666-6666-6666-6666-666666666666",
      chunk_job_id: CHUNK_JOB_RESPONSE.id,
      parsed_document_id: PARSED_DOCUMENT_RESPONSE.id,
      owner_user_id: "00000000-0000-0000-0000-000000000001",
      sequence_index: 0,
      text: "Chunk 0 explains retrieval.",
      contextualized_text: "Course Notes\nChunk 0 explains retrieval.",
      token_count: 10,
      heading_path: ["Course Notes", "Retrieval"],
      page_numbers: [1],
      chunk_type: "text",
      source_segment_indices: [0],
      metadata: { docling_ref: "#/texts/0" },
      created_at: "2026-06-12T00:00:03Z",
    },
    {
      id: "77777777-7777-7777-7777-777777777777",
      chunk_job_id: CHUNK_JOB_RESPONSE.id,
      parsed_document_id: PARSED_DOCUMENT_RESPONSE.id,
      owner_user_id: "00000000-0000-0000-0000-000000000001",
      sequence_index: 1,
      text: "Chunk 1 explains citations.",
      contextualized_text: "Course Notes\nChunk 1 explains citations.",
      token_count: 12,
      heading_path: ["Course Notes", "Citations"],
      page_numbers: [2],
      chunk_type: "text",
      source_segment_indices: [1],
      metadata: { docling_ref: "#/texts/1" },
      created_at: "2026-06-12T00:00:03Z",
    },
  ],
  total: 2,
  offset: 0,
  limit: 20,
}

function mockSuccessfulUpload() {
  mocks.uploadFileMock.mockResolvedValue(UPLOADED_FILE_RESPONSE)
}

async function submitCourseNotes(wrapper: VueWrapper) {
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
}

describe("HomeView", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mocks.refreshHealthMock.mockReset()
    mocks.loadCurrentUserMock.mockReset()
    mocks.uploadFileMock.mockReset()
    mocks.createDocumentParseJobMock.mockReset()
    mocks.getDocumentParseJobMock.mockReset()
    mocks.getParsedDocumentForUploadMock.mockReset()
    mocks.getDocumentChunkJobMock.mockReset()
    mocks.getLatestParsedDocumentChunkJobMock.mockReset()
    mocks.getParsedDocumentChunksMock.mockReset()
    mocks.getDocumentChunkMock.mockReset()
    mocks.rechunkParsedDocumentMock.mockReset()
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
    mocks.getParsedDocumentForUploadMock.mockResolvedValue(PARSED_DOCUMENT_RESPONSE)
    mocks.getDocumentChunkJobMock.mockResolvedValue(CHUNK_JOB_RESPONSE)
    mocks.getLatestParsedDocumentChunkJobMock.mockResolvedValue(CHUNK_JOB_RESPONSE)
    mocks.getParsedDocumentChunksMock.mockResolvedValue(CHUNK_PAGE_RESPONSE)
    mocks.getDocumentChunkMock.mockResolvedValue(CHUNK_PAGE_RESPONSE.items[0])
    mocks.rechunkParsedDocumentMock.mockResolvedValue({
      ...CHUNK_JOB_RESPONSE,
      status: "queued",
      finished_at: null,
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

  // 测试：解析成功后若分块仍在运行，页面应展示分块中并禁用重复重分块触发。
  it("shows chunking progress after parsing succeeds and disables duplicate rechunk", async () => {
    mockSuccessfulUpload()
    mocks.getParsedDocumentChunksMock.mockResolvedValue({
      items: [],
      total: 0,
      offset: 0,
      limit: 20,
    })
    const runningChunkJob = {
      ...CHUNK_JOB_RESPONSE,
      status: "running",
      finished_at: null,
    }
    mocks.getLatestParsedDocumentChunkJobMock.mockResolvedValue(runningChunkJob)
    mocks.getDocumentChunkJobMock.mockResolvedValue(runningChunkJob)
    const wrapper = mount(HomeView)

    await submitCourseNotes(wrapper)

    expect(mocks.getParsedDocumentForUploadMock).toHaveBeenCalledWith(
      UPLOADED_FILE_RESPONSE.id,
    )
    expect(mocks.getLatestParsedDocumentChunkJobMock).toHaveBeenCalledWith(
      PARSED_DOCUMENT_RESPONSE.id,
    )
    expect(mocks.getDocumentChunkJobMock).toHaveBeenCalledWith(CHUNK_JOB_RESPONSE.id)
    expect(mocks.getDocumentChunkJobMock).not.toHaveBeenCalledWith(
      PARSED_DOCUMENT_RESPONSE.id,
    )
    expect(wrapper.get('[data-testid="chunk-status"]').text()).toContain(
      "分块中",
    )
    expect(wrapper.get('[data-testid="rechunk-button"]').attributes()).toHaveProperty(
      "disabled",
    )
  })

  // 测试：运行中的初次分块成功后，页面应自动刷新为分块成功并加载预览。
  it("updates running initial chunking to completion and loads the preview", async () => {
    mockSuccessfulUpload()
    mocks.getParsedDocumentChunksMock
      .mockResolvedValueOnce({
        items: [],
        total: 0,
        offset: 0,
        limit: 20,
      })
      .mockResolvedValueOnce(CHUNK_PAGE_RESPONSE)
    mocks.getLatestParsedDocumentChunkJobMock.mockResolvedValue({
      ...CHUNK_JOB_RESPONSE,
      status: "running",
      finished_at: null,
    })
    mocks.getDocumentChunkJobMock.mockResolvedValue({
      ...CHUNK_JOB_RESPONSE,
      status: "succeeded",
    })
    const wrapper = mount(HomeView)

    await submitCourseNotes(wrapper)
    await flushPromises()

    expect(mocks.getDocumentChunkJobMock).toHaveBeenCalledWith(CHUNK_JOB_RESPONSE.id)
    expect(mocks.getParsedDocumentChunksMock).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[data-testid="chunk-status"]').text()).toContain(
      "分块成功",
    )
    expect(wrapper.get('[data-testid="chunk-preview"]').text()).toContain(
      "Chunk 0 explains retrieval.",
    )
  })

  // 测试：分块成功后展示成功反馈和预览入口。
  it("shows chunk completion and a preview entry after chunks are available", async () => {
    mockSuccessfulUpload()
    const wrapper = mount(HomeView)

    await submitCourseNotes(wrapper)

    expect(mocks.getParsedDocumentChunksMock).toHaveBeenCalledWith(
      PARSED_DOCUMENT_RESPONSE.id,
      expect.objectContaining({ offset: 0, limit: 20 }),
    )
    expect(wrapper.get('[data-testid="chunk-status"]').text()).toContain(
      "分块成功",
    )
    expect(wrapper.get('[data-testid="chunk-preview"]').text()).toContain(
      "Chunk 0 explains retrieval.",
    )
  })

  // 测试：分块失败时展示可理解的错误反馈，并保留重新分块入口。
  it("shows chunking failure feedback and keeps rechunk available", async () => {
    mockSuccessfulUpload()
    mocks.getLatestParsedDocumentChunkJobMock.mockResolvedValue({
      ...CHUNK_JOB_RESPONSE,
      status: "failed",
      error_message: "Parser did not provide a memory document object",
    })
    mocks.getParsedDocumentChunksMock.mockResolvedValue({
      items: [],
      total: 0,
      offset: 0,
      limit: 20,
    })
    const wrapper = mount(HomeView)

    await submitCourseNotes(wrapper)

    expect(wrapper.get('[data-testid="chunk-status"]').text()).toContain(
      "分块失败",
    )
    expect(wrapper.get('[data-testid="chunk-status"]').text()).toContain(
      "Parser did not provide a memory document object",
    )
    expect(wrapper.get('[data-testid="rechunk-button"]').attributes("disabled")).toBeUndefined()
  })

  // 测试：重新分块运行中应保留旧预览，并禁用重复触发。
  it("keeps the old preview visible while rechunk is running", async () => {
    mockSuccessfulUpload()
    mocks.rechunkParsedDocumentMock.mockResolvedValue({
      ...CHUNK_JOB_RESPONSE,
      id: "88888888-8888-8888-8888-888888888888",
      status: "running",
      finished_at: null,
    })
    mocks.getDocumentChunkJobMock.mockResolvedValue({
      ...CHUNK_JOB_RESPONSE,
      id: "88888888-8888-8888-8888-888888888888",
      status: "running",
      finished_at: null,
    })
    const wrapper = mount(HomeView)

    await submitCourseNotes(wrapper)
    await wrapper.get('[data-testid="rechunk-button"]').trigger("click")
    await flushPromises()

    expect(mocks.rechunkParsedDocumentMock).toHaveBeenCalledWith(
      PARSED_DOCUMENT_RESPONSE.id,
      expect.any(Object),
    )
    expect(wrapper.get('[data-testid="chunk-status"]').text()).toContain(
      "重新分块中",
    )
    expect(wrapper.get('[data-testid="chunk-preview"]').text()).toContain(
      "Chunk 0 explains retrieval.",
    )
    expect(wrapper.get('[data-testid="rechunk-button"]').attributes()).toHaveProperty(
      "disabled",
    )
  })

  // 测试：重新分块失败时旧预览仍然可见，并展示新作业失败原因。
  it("keeps the old preview when rechunk fails", async () => {
    mockSuccessfulUpload()
    mocks.rechunkParsedDocumentMock.mockResolvedValue({
      ...CHUNK_JOB_RESPONSE,
      id: "88888888-8888-8888-8888-888888888888",
      status: "queued",
      finished_at: null,
    })
    mocks.getDocumentChunkJobMock.mockResolvedValue({
      ...CHUNK_JOB_RESPONSE,
      id: "88888888-8888-8888-8888-888888888888",
      status: "failed",
      error_message: "tokenizer unavailable",
    })
    const wrapper = mount(HomeView)

    await submitCourseNotes(wrapper)
    await wrapper.get('[data-testid="rechunk-button"]').trigger("click")
    await flushPromises()

    expect(wrapper.get('[data-testid="chunk-status"]').text()).toContain(
      "重新分块失败",
    )
    expect(wrapper.get('[data-testid="chunk-status"]').text()).toContain(
      "tokenizer unavailable",
    )
    expect(wrapper.get('[data-testid="chunk-preview"]').text()).toContain(
      "Chunk 0 explains retrieval.",
    )
  })

  // 测试：分块查询遇到权限或网络错误时，页面应展示错误反馈。
  it("shows chunk permission or network errors", async () => {
    mockSuccessfulUpload()
    mocks.getParsedDocumentChunksMock.mockRejectedValue(new Error("请求失败：403"))
    const wrapper = mount(HomeView)

    await submitCourseNotes(wrapper)

    expect(wrapper.get('[data-testid="chunk-status"]').text()).toContain(
      "请求失败：403",
    )
  })

  // 测试：chunk 预览按顺序展示正文、标题路径、页码和 token 计数。
  it("renders chunk preview in order with text, headings, pages, and token counts", async () => {
    mockSuccessfulUpload()
    const wrapper = mount(HomeView)

    await submitCourseNotes(wrapper)

    const previewItems = wrapper.findAll('[data-testid="chunk-preview-item"]')
    expect(previewItems).toHaveLength(2)
    expect(previewItems[0].text()).toContain("Chunk 0 explains retrieval.")
    expect(previewItems[0].text()).toContain("Course Notes / Retrieval")
    expect(previewItems[0].text()).toContain("第 1 页")
    expect(previewItems[0].text()).toContain("10 tokens")
    expect(previewItems[1].text()).toContain("Chunk 1 explains citations.")
    expect(previewItems[1].text()).toContain("第 2 页")
    expect(previewItems[1].text()).toContain("12 tokens")
  })

  // 测试：没有可用 chunks 时展示稳定空状态，而不是把空列表误报为检索可用。
  it("shows an empty chunk preview state", async () => {
    mockSuccessfulUpload()
    mocks.getParsedDocumentChunksMock.mockResolvedValue({
      items: [],
      total: 0,
      offset: 0,
      limit: 20,
    })
    const wrapper = mount(HomeView)

    await submitCourseNotes(wrapper)

    expect(wrapper.get('[data-testid="chunk-preview-empty"]').text()).toContain(
      "暂无分块可预览",
    )
  })

  // 测试：分块成功文案不承诺 embedding、语义检索或 RAG 问答已可用。
  it("does not describe chunk completion as retrieval or RAG readiness", async () => {
    mockSuccessfulUpload()
    const wrapper = mount(HomeView)

    await submitCourseNotes(wrapper)

    const chunkPanelText = wrapper.get('[data-testid="chunk-panel"]').text()
    expect(chunkPanelText).toContain("分块成功")
    expect(chunkPanelText).not.toContain("embedding")
    expect(chunkPanelText).not.toContain("向量索引")
    expect(chunkPanelText).not.toContain("语义检索")
    expect(chunkPanelText).not.toContain("RAG")
    expect(chunkPanelText).not.toContain("问答可用")
  })
})
