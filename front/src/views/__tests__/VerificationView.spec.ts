import { mount, flushPromises } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { nextTick } from "vue"

// ── Mock setup (must use vi.hoisted so factories are available in hoisted vi.mock) ──

const {
  mockListParsedDocuments,
  mockFetchPipelineVerification,
  mockLoggerDebug,
  mockLoggerInfo,
  mockLoggerWarn,
  mockLoggerError,
} = vi.hoisted(() => ({
  mockListParsedDocuments: vi.fn(),
  mockFetchPipelineVerification: vi.fn(),
  mockLoggerDebug: vi.fn(),
  mockLoggerInfo: vi.fn(),
  mockLoggerWarn: vi.fn(),
  mockLoggerError: vi.fn(),
}))

vi.mock("../../api/documentParsing", () => ({
  listParsedDocuments: (...args: unknown[]) => mockListParsedDocuments(...args),
}))

vi.mock("../../api/pipelineVerification", () => ({
  fetchPipelineVerification: (...args: unknown[]) => mockFetchPipelineVerification(...args),
}))

vi.mock("../../shared/logger", () => ({
  createLogger: vi.fn(() => ({
    debug: mockLoggerDebug,
    info: mockLoggerInfo,
    warn: mockLoggerWarn,
    error: mockLoggerError,
  })),
  getRingBuffer: vi.fn(() => ({ getAll: () => [] })),
}))

// Lazy import after mocks are established
const { default: VerificationView } = await import("../VerificationView.vue")

// ── Test data factories ──────────────────────────────────────────────────

/** 构建一份完整的成功验证响应，所有 7 项检查均通过。 */
function buildSuccessResponse(overrides?: Partial<{
  docTitle: string
  pairCount: number
  checksPassed: boolean
}>): Record<string, unknown> {
  const pairCount = overrides?.pairCount ?? 3
  const checksPassed = overrides?.checksPassed ?? true

  const pairs = []
  for (let i = 0; i < pairCount; i++) {
    pairs.push({
      sequence_index: i,
      chunk: {
        id: `chunk-${i}`,
        text: `这是第 ${i} 个分块的示例文本内容，用于验证分块-向量对照表的正确渲染。包含足够的长度以便测试文本截断功能。`,
        contextualized_text: i === 0 ? null : `上下文增强文本 ${i}`,
        text_source: i % 2 === 0 ? "inline" : "file",
        token_count: 128 + i * 16,
        heading_path: ["第一章", "第一节"],
        page_numbers: [i + 1],
      },
      embedding: {
        id: `emb-${i}`,
        model: "text-embedding-3-small",
        dimensions: 1536,
        vector_preview: [0.012345, -0.023456, 0.034567, -0.045678, 0.056789],
        token_count: 120 + i * 10,
      },
    })
  }

  const checks = [
    {
      name: "chunk_embedding_pairing",
      passed: true,
      message: checksPassed ? "3/3 分块与向量一一对应，无孤儿记录" : "存在 1 条孤儿 embedding",
    },
    {
      name: "dimension_consistency",
      passed: true,
      message: "所有 3 条向量维度均为 1536",
    },
    {
      name: "sequence_continuity",
      passed: checksPassed,
      message: checksPassed
        ? "sequence_index 从 0 到 2 连续"
        : "sequence_index 存在跳号，缺失: [1]",
    },
    {
      name: "chunk_text_availability",
      passed: true,
      message: "3/3 分块文本可读取（2 内联 + 1 文件存储）",
    },
    {
      name: "contextualized_text_availability",
      passed: true,
      message: "3/3 上下文增强文本可读取",
    },
    {
      name: "token_count_consistency",
      passed: true,
      message: "所有 chunk 和 embedding 的 token_count 均有效",
    },
    {
      name: "model_consistency",
      passed: true,
      message: "所有 embedding 使用同一模型: text-embedding-3-small",
    },
  ]

  // 如果需要部分检查失败，修改个别检查项
  if (!checksPassed) {
    checks[0].passed = false
    checks[2].passed = false
  }

  return {
    document: {
      parsed_document_id: "pd-001",
      title: overrides?.docTitle ?? "测试文档.pdf",
      original_filename: "测试文档.pdf",
      content_type: "application/pdf",
      byte_size: 102400,
    },
    pipeline: {
      parse_job: { id: "pj-001", status: "succeeded" },
      chunk_job: {
        id: "cj-001",
        status: "succeeded",
        chunker_name: "RecursiveCharacterTextSplitter",
        chunk_count: pairCount,
      },
      embedding_job: {
        id: "ej-001",
        status: "succeeded",
        model: "text-embedding-3-small",
        dimensions: 1536,
        embedding_count: pairCount,
      },
    },
    verification: {
      passed: checksPassed,
      total_checks: 7,
      passed_checks: checksPassed ? 7 : 5,
      checks,
    },
    pairs,
    stats: {
      total_pairs: pairCount,
      total_chunk_tokens: 432,
      total_embedding_tokens: 390,
      inline_text_count: 2,
      file_storage_text_count: 1,
      embedding_dimensions: 1536,
      embedding_model: "text-embedding-3-small",
    },
  }
}

/** 构建 ParsedDocument 列表。 */
function buildParsedDocuments(count: number) {
  const docs = []
  for (let i = 1; i <= count; i++) {
    docs.push({
      id: `pd-00${i}`,
      uploaded_file_id: `uf-00${i}`,
      parse_job_id: `pj-00${i}`,
      owner_user_id: "user-001",
      source_checksum_sha256: null,
      markdown_storage_key: `md-00${i}`,
      text_storage_key: `txt-00${i}`,
      docling_json_storage_key: `json-00${i}`,
      title: `测试文档 ${i}.pdf`,
      page_count: 10 + i,
      metadata: null,
      segment_count: 5 * i,
      created_at: "2026-07-22T00:00:00Z",
    })
  }
  return docs
}

describe("VerificationView", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // 默认：3 个已解析文档，验证成功
    mockListParsedDocuments.mockResolvedValue(buildParsedDocuments(3))
    mockFetchPipelineVerification.mockResolvedValue(buildSuccessResponse())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  // ── 7.1.1 文档选择器渲染 ────────────────────────────────────────────

  describe("文档选择器渲染", () => {
    it("页面挂载后自动调用 listParsedDocuments 并填充下拉框选项", async () => {
      const wrapper = mount(VerificationView)
      await flushPromises()

      // 验证 listParsedDocuments 被调用
      expect(mockListParsedDocuments).toHaveBeenCalledTimes(1)

      // 下拉框应存在
      const select = wrapper.find('[data-testid="document-select"]')
      expect(select.exists()).toBe(true)

      // 应包含默认提示 option + 3 个文档 option
      const options = select.findAll("option")
      expect(options).toHaveLength(4) // "请选择文档" + 3 docs
      expect(options[0].text()).toContain("请选择文档")
      expect(options[1].text()).toContain("测试文档 1.pdf")
      expect(options[2].text()).toContain("测试文档 2.pdf")
      expect(options[3].text()).toContain("测试文档 3.pdf")
    })

    it("每个文档选项包含 segment_count 信息", async () => {
      const wrapper = mount(VerificationView)
      await flushPromises()

      const options = wrapper.find('[data-testid="document-select"]').findAll("option")
      expect(options[1].text()).toContain("(5 段)")
      expect(options[2].text()).toContain("(10 段)")
      expect(options[3].text()).toContain("(15 段)")
    })
  })

  // ── 7.1.2 验证按钮存在 ──────────────────────────────────────────────

  describe("验证按钮", () => {
    it("渲染「执行验证」按钮", async () => {
      const wrapper = mount(VerificationView)
      await flushPromises()

      const button = wrapper.find('[data-testid="verify-button"]')
      expect(button.exists()).toBe(true)
      expect(button.text()).toBe("执行验证")
    })

    it("未选择文档时按钮处于禁用状态", async () => {
      const wrapper = mount(VerificationView)
      await flushPromises()

      const button = wrapper.find('[data-testid="verify-button"]')
      expect(button.attributes("disabled")).toBeDefined()
    })

    it("选择文档后按钮变为可用状态", async () => {
      const wrapper = mount(VerificationView)
      await flushPromises()

      const select = wrapper.find('[data-testid="document-select"]')
      await select.setValue("pd-001")

      const button = wrapper.find('[data-testid="verify-button"]')
      expect(button.attributes("disabled")).toBeUndefined()
    })
  })

  // ── 7.1.3 点击验证后显示加载指示器 ──────────────────────────────────

  describe("验证加载状态", () => {
    it("点击验证按钮后显示骨架屏加载指示器", async () => {
      // 使 fetchPipelineVerification 永不 resolve，保持在加载状态
      let resolveLater!: (value: unknown) => void
      mockFetchPipelineVerification.mockReturnValue(
        new Promise((resolve) => { resolveLater = resolve }),
      )

      const wrapper = mount(VerificationView)
      await flushPromises()

      // 选择文档
      await wrapper.find('[data-testid="document-select"]').setValue("pd-001")
      // 点击验证
      await wrapper.find('[data-testid="verify-button"]').trigger("click")
      await nextTick()

      // 骨架屏应显示
      expect(wrapper.find('[data-testid="verification-loading"]').exists()).toBe(true)

      // 清理
      resolveLater(buildSuccessResponse())
      await flushPromises()
    })

    it("加载期间按钮被禁用", async () => {
      let resolveLater!: (value: unknown) => void
      mockFetchPipelineVerification.mockReturnValue(
        new Promise((resolve) => { resolveLater = resolve }),
      )

      const wrapper = mount(VerificationView)
      await flushPromises()

      await wrapper.find('[data-testid="document-select"]').setValue("pd-001")
      await wrapper.find('[data-testid="verify-button"]').trigger("click")
      await nextTick()

      const button = wrapper.find('[data-testid="verify-button"]')
      expect(button.attributes("disabled")).toBeDefined()

      resolveLater(buildSuccessResponse())
      await flushPromises()
    })
  })

  // ── 7.1.4 API 返回成功时正确渲染摘要卡片和对照表 ────────────────────

  describe("成功响应渲染", () => {
    it("验证成功后渲染文档信息面板", async () => {
      const wrapper = mount(VerificationView)
      await flushPromises()

      await wrapper.find('[data-testid="document-select"]').setValue("pd-001")
      await wrapper.find('[data-testid="verify-button"]').trigger("click")
      await flushPromises()

      const docInfo = wrapper.find('[data-testid="document-info"]')
      expect(docInfo.exists()).toBe(true)
      expect(docInfo.text()).toContain("测试文档.pdf")
      expect(docInfo.text()).toContain("pd-001")
    })

    it("验证成功后渲染 Pipeline 链路展示", async () => {
      const wrapper = mount(VerificationView)
      await flushPromises()

      await wrapper.find('[data-testid="document-select"]').setValue("pd-001")
      await wrapper.find('[data-testid="verify-button"]').trigger("click")
      await flushPromises()

      const stages = wrapper.find('[data-testid="pipeline-stages"]')
      expect(stages.exists()).toBe(true)
      expect(stages.text()).toContain("解析")
      expect(stages.text()).toContain("分块")
      expect(stages.text()).toContain("向量化")
      expect(stages.text()).toContain("已完成")
    })

    it("验证成功后渲染验证摘要面板，显示 7 项检查", async () => {
      const wrapper = mount(VerificationView)
      await flushPromises()

      await wrapper.find('[data-testid="document-select"]').setValue("pd-001")
      await wrapper.find('[data-testid="verify-button"]').trigger("click")
      await flushPromises()

      const summary = wrapper.find('[data-testid="verification-summary"]')
      expect(summary.exists()).toBe(true)
      expect(summary.text()).toContain("7/7")
      expect(summary.text()).toContain("通过")

      const checkItems = wrapper.findAll('[data-testid="check-item"]')
      expect(checkItems).toHaveLength(7)
    })

    it("验证成功后渲染统计卡片", async () => {
      const wrapper = mount(VerificationView)
      await flushPromises()

      await wrapper.find('[data-testid="document-select"]').setValue("pd-001")
      await wrapper.find('[data-testid="verify-button"]').trigger("click")
      await flushPromises()

      const stats = wrapper.find('[data-testid="verification-stats"]')
      expect(stats.exists()).toBe(true)
      expect(stats.text()).toContain("3") // total_pairs
      expect(stats.text()).toContain("text-embedding-3-small")
    })

    it("验证成功后渲染分块-向量对照表，每行包含序号和文本", async () => {
      const wrapper = mount(VerificationView)
      await flushPromises()

      await wrapper.find('[data-testid="document-select"]').setValue("pd-001")
      await wrapper.find('[data-testid="verify-button"]').trigger("click")
      await flushPromises()

      const table = wrapper.find('[data-testid="pairs-table"]')
      expect(table.exists()).toBe(true)

      const rows = wrapper.findAll('[data-testid="pair-row"]')
      expect(rows).toHaveLength(3)
      expect(rows[0].text()).toContain("#0")
      expect(rows[1].text()).toContain("#1")
      expect(rows[2].text()).toContain("#2")
    })

    it("对照表中文本超过 150 字符时截断并显示省略号", async () => {
      const response = buildSuccessResponse({ pairCount: 1 }) as Record<string, unknown>
      const pairs = response.pairs as Array<Record<string, unknown>>
      const chunk = pairs[0].chunk as Record<string, unknown>
      chunk.text = "A".repeat(200)
      mockFetchPipelineVerification.mockResolvedValue(response)

      const wrapper = mount(VerificationView)
      await flushPromises()

      await wrapper.find('[data-testid="document-select"]').setValue("pd-001")
      await wrapper.find('[data-testid="verify-button"]').trigger("click")
      await flushPromises()

      const row = wrapper.find('[data-testid="pair-row"]')
      expect(row.exists()).toBe(true)
      // 文本应被截断（150 字符 + "…"）
      expect(row.text()).toContain("…")
      expect(row.text()).not.toContain("A".repeat(200))
    })
  })

  // ── 7.1.5 passed/failed 两种检查状态的不同视觉呈现 ─────────────────

  describe("检查状态视觉呈现", () => {
    it("全部通过时显示绿色通过样式", async () => {
      const wrapper = mount(VerificationView)
      await flushPromises()

      await wrapper.find('[data-testid="document-select"]').setValue("pd-001")
      await wrapper.find('[data-testid="verify-button"]').trigger("click")
      await flushPromises()

      // 汇总标签应为绿色
      const summary = wrapper.find('[data-testid="verification-summary"]')
      expect(summary.find(".bg-emerald-50").exists()).toBe(true)
      expect(summary.text()).toContain("7/7")

      // 所有检查项应标记为"通过"
      const checkItems = wrapper.findAll('[data-testid="check-item"]')
      for (const item of checkItems) {
        expect(item.find(".bg-emerald-100").exists()).toBe(true)
        expect(item.text()).toContain("通过")
      }
    })

    it("部分检查失败时显示红色失败样式", async () => {
      mockFetchPipelineVerification.mockResolvedValue(
        buildSuccessResponse({ checksPassed: false }),
      )

      const wrapper = mount(VerificationView)
      await flushPromises()

      await wrapper.find('[data-testid="document-select"]').setValue("pd-001")
      await wrapper.find('[data-testid="verify-button"]').trigger("click")
      await flushPromises()

      const summary = wrapper.find('[data-testid="verification-summary"]')
      // 汇总标签应为红色（因为 passed=false）
      expect(summary.find(".bg-red-50").exists()).toBe(true)
      expect(summary.text()).toContain("5/7")

      // 应同时存在"通过"和"失败"标签
      const checkItems = wrapper.findAll('[data-testid="check-item"]')
      const passLabels = checkItems.filter((item) => item.text().includes("通过"))
      const failLabels = checkItems.filter((item) => item.text().includes("失败"))
      expect(passLabels.length).toBeGreaterThan(0)
      expect(failLabels.length).toBeGreaterThan(0)

      // 失败项应为红色背景
      const failItem = checkItems.find((item) => item.text().includes("失败"))
      expect(failItem?.find(".bg-red-100").exists()).toBe(true)
    })

    it("检查项中文名称映射正确", async () => {
      const wrapper = mount(VerificationView)
      await flushPromises()

      await wrapper.find('[data-testid="document-select"]').setValue("pd-001")
      await wrapper.find('[data-testid="verify-button"]').trigger("click")
      await flushPromises()

      const checkItems = wrapper.findAll('[data-testid="check-item"]')
      const labels = checkItems.map((item) => item.text())
      expect(labels.some((l) => l.includes("分块-向量对应关系"))).toBe(true)
      expect(labels.some((l) => l.includes("向量维度一致性"))).toBe(true)
      expect(labels.some((l) => l.includes("序号连续性"))).toBe(true)
      expect(labels.some((l) => l.includes("分块文本可读性"))).toBe(true)
      expect(labels.some((l) => l.includes("上下文增强文本可读性"))).toBe(true)
      expect(labels.some((l) => l.includes("Token 数有效性"))).toBe(true)
      expect(labels.some((l) => l.includes("嵌入模型一致性"))).toBe(true)
    })
  })

  // ── 7.1.6 API 返回 404 时显示错误详情 ───────────────────────────────

  describe("404 错误处理", () => {
    it("API 返回 404 时显示错误状态码和详情", async () => {
      // Use mockImplementationOnce to ensure the rejection takes priority over
      // the default mockResolvedValue set in beforeEach.
      mockFetchPipelineVerification.mockImplementationOnce(() =>
        Promise.reject(
          Object.assign(new Error("Parsed document not found"), {
            status: 404,
            detail: "Parsed document not found",
          }),
        ),
      )

      const wrapper = mount(VerificationView)
      await flushPromises()

      await wrapper.find('[data-testid="document-select"]').setValue("pd-001")
      await wrapper.find('[data-testid="verify-button"]').trigger("click")
      await flushPromises()

      const errorBox = wrapper.find('[data-testid="verification-error"]')
      expect(errorBox.exists()).toBe(true)
      expect(errorBox.text()).toContain("404")
      expect(errorBox.text()).toContain("Parsed document not found")
    })

    it("404 且 detail 包含 chunk job 时显示分块处理建议", async () => {
      const error = Object.assign(
        new Error("No succeeded chunk job found for this document"),
        { status: 404, detail: "No succeeded chunk job found for this document" },
      )
      mockFetchPipelineVerification.mockRejectedValue(error)

      const wrapper = mount(VerificationView)
      await flushPromises()

      await wrapper.find('[data-testid="document-select"]').setValue("pd-001")
      await wrapper.find('[data-testid="verify-button"]').trigger("click")
      await flushPromises()

      const errorBox = wrapper.find('[data-testid="verification-error"]')
      expect(errorBox.text()).toContain("该文档尚未完成分块处理")
      expect(errorBox.text()).toContain("请等待分块作业完成后再试")
    })

    it("404 且 detail 包含 embedding job 时显示向量化处理建议", async () => {
      const error = Object.assign(
        new Error("No succeeded embedding job found for this document"),
        { status: 404, detail: "No succeeded embedding job found for this document" },
      )
      mockFetchPipelineVerification.mockRejectedValue(error)

      const wrapper = mount(VerificationView)
      await flushPromises()

      await wrapper.find('[data-testid="document-select"]').setValue("pd-001")
      await wrapper.find('[data-testid="verify-button"]').trigger("click")
      await flushPromises()

      const errorBox = wrapper.find('[data-testid="verification-error"]')
      expect(errorBox.text()).toContain("该文档已完成分块但尚未向量化")
      expect(errorBox.text()).toContain("请等待向量化作业完成后再试")
    })

    it("404 但非 pipeline 阶段错误时显示通用建议", async () => {
      const error = Object.assign(new Error("Some other not found"), {
        status: 404,
        detail: "Some other not found",
      })
      mockFetchPipelineVerification.mockRejectedValue(error)

      const wrapper = mount(VerificationView)
      await flushPromises()

      await wrapper.find('[data-testid="document-select"]').setValue("pd-001")
      await wrapper.find('[data-testid="verify-button"]').trigger("click")
      await flushPromises()

      const errorBox = wrapper.find('[data-testid="verification-error"]')
      expect(errorBox.text()).toContain("请确认所选文档已完整经过解析、分块和向量化流程")
    })
  })

  // ── 7.1.7 无文档时的空状态提示 ──────────────────────────────────────

  describe("空状态提示", () => {
    it("无已解析文档时显示空状态提示", async () => {
      mockListParsedDocuments.mockResolvedValue([])

      const wrapper = mount(VerificationView)
      await flushPromises()

      const emptyState = wrapper.find('[data-testid="documents-empty"]')
      expect(emptyState.exists()).toBe(true)
      expect(emptyState.text()).toContain("暂无已解析文档")
      expect(emptyState.text()).toContain("请先在首页上传并解析文档")
    })

    it("无文档时选择器区域不显示下拉框", async () => {
      mockListParsedDocuments.mockResolvedValue([])

      const wrapper = mount(VerificationView)
      await flushPromises()

      expect(wrapper.find('[data-testid="document-select"]').exists()).toBe(false)
    })
  })

  // ── 7.1.8 API 返回 503 时的错误提示 ─────────────────────────────────

  describe("503 错误处理", () => {
    it("API 返回 503 时显示错误状态码和详情", async () => {
      const error = Object.assign(new Error("Current user is unavailable"), {
        status: 503,
        detail: "Current user is unavailable",
      })
      mockFetchPipelineVerification.mockRejectedValue(error)

      const wrapper = mount(VerificationView)
      await flushPromises()

      await wrapper.find('[data-testid="document-select"]').setValue("pd-001")
      await wrapper.find('[data-testid="verify-button"]').trigger("click")
      await flushPromises()

      const errorBox = wrapper.find('[data-testid="verification-error"]')
      expect(errorBox.exists()).toBe(true)
      expect(errorBox.text()).toContain("503")
      expect(errorBox.text()).toContain("Current user is unavailable")
    })
  })

  // ── 边界情况 ─────────────────────────────────────────────────────────

  describe("边界情况", () => {
    it("文档加载失败时显示错误信息及重试按钮", async () => {
      mockListParsedDocuments.mockRejectedValue(new Error("网络请求失败"))

      const wrapper = mount(VerificationView)
      await flushPromises()

      const errorBox = wrapper.find('[data-testid="documents-error"]')
      expect(errorBox.exists()).toBe(true)
      expect(errorBox.text()).toContain("网络请求失败")

      // 应显示重试按钮
      const retryButton = errorBox.find("button")
      expect(retryButton.exists()).toBe(true)
      expect(retryButton.text()).toBe("重试")
    })

    it("验证错误不是带 status/detail 的特定 Error 时仍能显示", async () => {
      mockFetchPipelineVerification.mockRejectedValue(new Error("网络连接已断开"))

      const wrapper = mount(VerificationView)
      await flushPromises()

      await wrapper.find('[data-testid="document-select"]').setValue("pd-001")
      await wrapper.find('[data-testid="verify-button"]').trigger("click")
      await flushPromises()

      const errorBox = wrapper.find('[data-testid="verification-error"]')
      expect(errorBox.exists()).toBe(true)
      expect(errorBox.text()).toContain("0")
      expect(errorBox.text()).toContain("网络连接已断开")
    })

    it("chunk 为 null 时显示「孤儿 embedding」提示", async () => {
      const response = buildSuccessResponse({ pairCount: 1 }) as Record<string, unknown>
      const pairs = response.pairs as Array<Record<string, unknown>>
      pairs[0].chunk = null
      // embedding 保留
      mockFetchPipelineVerification.mockResolvedValue(response)

      const wrapper = mount(VerificationView)
      await flushPromises()

      await wrapper.find('[data-testid="document-select"]').setValue("pd-001")
      await wrapper.find('[data-testid="verify-button"]').trigger("click")
      await flushPromises()

      const row = wrapper.find('[data-testid="pair-row"]')
      expect(row.text()).toContain("孤儿 embedding")
    })

    it("embedding 为 null 时显示「孤儿 chunk」提示", async () => {
      const response = buildSuccessResponse({ pairCount: 1 }) as Record<string, unknown>
      const pairs = response.pairs as Array<Record<string, unknown>>
      pairs[0].embedding = null
      mockFetchPipelineVerification.mockResolvedValue(response)

      const wrapper = mount(VerificationView)
      await flushPromises()

      await wrapper.find('[data-testid="document-select"]').setValue("pd-001")
      await wrapper.find('[data-testid="verify-button"]').trigger("click")
      await flushPromises()

      const row = wrapper.find('[data-testid="pair-row"]')
      expect(row.text()).toContain("孤儿 chunk")
    })
  })

  // ── 4.7 重构 RED 测试：顶部导航栏 ───────────────────────────────────

  describe("顶部导航栏（视觉重构）", () => {
    it("渲染顶部导航栏容器", async () => {
      const wrapper = mount(VerificationView)
      await flushPromises()

      const navbar = wrapper.find('[data-testid="verify-navbar"]')
      expect(navbar.exists()).toBe(true)
    })

    it("顶部导航栏包含 knowra Logo（链接至 /）", async () => {
      const wrapper = mount(VerificationView)
      await flushPromises()

      const logo = wrapper.find('[data-testid="verify-nav-logo"]')
      expect(logo.exists()).toBe(true)
      expect(logo.text()).toContain("knowra")
    })

    it("顶部导航栏包含「流程验证」页面标题", async () => {
      const wrapper = mount(VerificationView)
      await flushPromises()

      const navbar = wrapper.find('[data-testid="verify-navbar"]')
      expect(navbar.text()).toContain("流程验证")
    })

    it("顶部导航栏包含返回首页链接", async () => {
      const wrapper = mount(VerificationView)
      await flushPromises()

      const backLink = wrapper.find('[data-testid="verify-nav-back"]')
      expect(backLink.exists()).toBe(true)
      expect(backLink.text()).toContain("返回首页")
    })
  })

  // ── 4.7 重构 RED 测试：品牌蓝按钮 ──────────────────────────────────

  describe("品牌蓝按钮样式（视觉重构）", () => {
    it("「执行验证」按钮使用品牌蓝配色", async () => {
      const wrapper = mount(VerificationView)
      await flushPromises()

      // 选择文档使按钮可用
      await wrapper.find('[data-testid="document-select"]').setValue("pd-001")

      const button = wrapper.find('[data-testid="verify-button"]')
      // 品牌蓝样式：应包含 bg-brand-700 类
      expect(button.classes()).toContain("bg-brand-700")
    })

    it("「执行验证」按钮 hover 时变深蓝", async () => {
      const wrapper = mount(VerificationView)
      await flushPromises()

      await wrapper.find('[data-testid="document-select"]').setValue("pd-001")

      const button = wrapper.find('[data-testid="verify-button"]')
      // hover 状态应包含 hover:bg-brand-800
      expect(button.classes()).toContain("hover:bg-brand-800")
    })

    it("禁用按钮使用灰色样式", async () => {
      const wrapper = mount(VerificationView)
      await flushPromises()

      // 未选择文档时按钮禁用
      const button = wrapper.find('[data-testid="verify-button"]')
      expect(button.attributes("disabled")).toBeDefined()
      expect(button.classes()).toContain("disabled:bg-neutral-200")
    })
  })

  // ── 4.7 重构 RED 测试：卡片圆角与阴影 ──────────────────────────────

  describe("卡片样式统一（视觉重构）", () => {
    it("文档选择器卡片使用 rounded-lg 圆角", async () => {
      const wrapper = mount(VerificationView)
      await flushPromises()

      const card = wrapper.find('[data-testid="document-selector"]')
      expect(card.classes()).toContain("rounded-lg")
    })

    it("验证结果面板卡片使用 rounded-lg 圆角", async () => {
      const wrapper = mount(VerificationView)
      await flushPromises()

      await wrapper.find('[data-testid="document-select"]').setValue("pd-001")
      await wrapper.find('[data-testid="verify-button"]').trigger("click")
      await flushPromises()

      const docInfo = wrapper.find('[data-testid="document-info"]')
      expect(docInfo.classes()).toContain("rounded-lg")
    })

    it("所有主要卡片使用 shadow-sm 阴影", async () => {
      const wrapper = mount(VerificationView)
      await flushPromises()

      const card = wrapper.find('[data-testid="document-selector"]')
      expect(card.classes()).toContain("shadow-sm")
    })
  })

  // ── 4.7 重构 RED 测试：现有功能不受影响 ─────────────────────────────

  describe("视觉重构不影响现有功能", () => {
    it("页面挂载后仍然自动加载已解析文档列表", async () => {
      mount(VerificationView)
      await flushPromises()

      expect(mockListParsedDocuments).toHaveBeenCalled()
    })

    it("选择文档后点击验证按钮依然触发验证流程", async () => {
      const wrapper = mount(VerificationView)
      await flushPromises()

      await wrapper.find('[data-testid="document-select"]').setValue("pd-001")
      await wrapper.find('[data-testid="verify-button"]').trigger("click")
      await flushPromises()

      expect(mockFetchPipelineVerification).toHaveBeenCalledWith("pd-001")
    })

    it("验证结果区域仍然包含所有必要面板", async () => {
      const wrapper = mount(VerificationView)
      await flushPromises()

      await wrapper.find('[data-testid="document-select"]').setValue("pd-001")
      await wrapper.find('[data-testid="verify-button"]').trigger("click")
      await flushPromises()

      // 所有验证结果区域应正常渲染
      expect(wrapper.find('[data-testid="document-info"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="pipeline-stages"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="verification-summary"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="verification-stats"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="pairs-table"]').exists()).toBe(true)
    })

    it("无文档时仍然显示空状态", async () => {
      mockListParsedDocuments.mockResolvedValue([])

      const wrapper = mount(VerificationView)
      await flushPromises()

      expect(wrapper.find('[data-testid="documents-empty"]').exists()).toBe(true)
      expect(wrapper.text()).toContain("暂无已解析文档")
    })

    it("验证错误仍然正常显示", async () => {
      mockFetchPipelineVerification.mockRejectedValue(
        Object.assign(new Error("Server error"), {
          status: 500,
          detail: "Server error",
        }),
      )

      const wrapper = mount(VerificationView)
      await flushPromises()

      await wrapper.find('[data-testid="document-select"]').setValue("pd-001")
      await wrapper.find('[data-testid="verify-button"]').trigger("click")
      await flushPromises()

      expect(wrapper.find('[data-testid="verification-error"]').exists()).toBe(true)
    })
  })
})
