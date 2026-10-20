import { flushPromises, mount } from "@vue/test-utils"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { makeParsedDocument } from "../../../__tests__/fixtures/search"

vi.mock("../../../shared/logger", () => ({
  createLogger: () => ({ debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() }),
  getRingBuffer: () => ({ push: vi.fn(), size: 0, getAll: () => [] }),
}))

const mockListParsedDocuments = vi.fn()

vi.mock("../../../api/documentParsing", () => ({
  listParsedDocuments: (...args: unknown[]) => mockListParsedDocuments(...args),
}))

async function mountKnowledgeInfo() {
  const { default: KnowledgeInfo } = await import("../KnowledgeInfo.vue")
  return mount(KnowledgeInfo)
}

describe("KnowledgeInfo 资料库分区", () => {
  beforeEach(() => {
    mockListParsedDocuments.mockReset()
  })

  // 验证挂载即调用只读接口获取已解析文档，且只调用一次
  it("挂载时调用 listParsedDocuments 一次", async () => {
    mockListParsedDocuments.mockResolvedValue([])
    await mountKnowledgeInfo()
    await flushPromises()

    expect(mockListParsedDocuments).toHaveBeenCalledTimes(1)
  })

  // 验证请求未返回时显示加载骨架，且不误报错误或空状态
  it("请求进行中显示加载状态", async () => {
    mockListParsedDocuments.mockReturnValue(new Promise(() => {}))
    const wrapper = await mountKnowledgeInfo()
    await flushPromises()

    expect(wrapper.find('[data-testid="knowledge-loading"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="knowledge-error"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="knowledge-empty"]').exists()).toBe(false)
  })

  // 验证有资料时显示已解析资料数量（3 条记录 → "3 份已解析资料"）
  it("有资料时显示已解析数量", async () => {
    mockListParsedDocuments.mockResolvedValue([
      makeParsedDocument({ id: "pd-1" }),
      makeParsedDocument({ id: "pd-2" }),
      makeParsedDocument({ id: "pd-3" }),
    ])
    const wrapper = await mountKnowledgeInfo()
    await flushPromises()

    expect(wrapper.find('[data-testid="knowledge-count"]').text()).toContain("3 份已解析资料")
    expect(wrapper.find('[data-testid="knowledge-loading"]').exists()).toBe(false)
  })

  // 验证空资料库给出上传引导而不是显示 0
  it("资料库为空时显示空状态与上传引导", async () => {
    mockListParsedDocuments.mockResolvedValue([])
    const wrapper = await mountKnowledgeInfo()
    await flushPromises()

    const empty = wrapper.find('[data-testid="knowledge-empty"]')
    expect(empty.exists()).toBe(true)
    expect(empty.text()).toContain("还没有已解析的资料")
    expect(empty.text()).toContain("上传")
    expect(wrapper.find('[data-testid="knowledge-count"]').exists()).toBe(false)
  })

  // 验证接口失败时显示明确错误和重试按钮
  it("加载失败时显示错误与重试按钮", async () => {
    mockListParsedDocuments.mockRejectedValue(new Error("服务不可用"))
    const wrapper = await mountKnowledgeInfo()
    await flushPromises()

    const error = wrapper.find('[data-testid="knowledge-error"]')
    expect(error.exists()).toBe(true)
    expect(error.text()).toContain("资料库状态获取失败")
    expect(wrapper.find('[data-testid="knowledge-retry"]').exists()).toBe(true)
  })

  // 验证点击重试会重新请求，成功后切换为数量展示
  it("点击重试再次请求并在成功后显示数量", async () => {
    mockListParsedDocuments
      .mockRejectedValueOnce(new Error("服务不可用"))
      .mockResolvedValueOnce([makeParsedDocument()])
    const wrapper = await mountKnowledgeInfo()
    await flushPromises()

    await wrapper.find('[data-testid="knowledge-retry"]').trigger("click")
    await flushPromises()

    expect(mockListParsedDocuments).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[data-testid="knowledge-error"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="knowledge-count"]').text()).toContain("1 份已解析资料")
  })

  // 验证提供进入 /verify 流程验证页的入口
  it("提供流程验证入口链接", async () => {
    mockListParsedDocuments.mockResolvedValue([makeParsedDocument()])
    const wrapper = await mountKnowledgeInfo()
    await flushPromises()

    const link = wrapper.find('[data-testid="knowledge-verify-link"]')
    expect(link.attributes("href")).toBe("/verify")
    expect(link.text()).toContain("流程验证")
  })
})
