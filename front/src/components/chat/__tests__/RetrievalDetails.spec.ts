import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import type { RewriteInfo } from "../../../api/search"
import { makeResponse, makeResult } from "../../../__tests__/fixtures/search"

const rewriteInfo: RewriteInfo = {
  original_query: "它的定义",
  rewritten_queries: [{ query: "特征值的定义", strategy: "normalize", duration_ms: 30, tokens: 12 }],
  strategies_used: ["normalize"],
  rewrite_time_ms: 30,
  cache_hit: false,
  error: null,
  rewrite_model: "deepseek-chat",
  intent: "factual",
  complexity: 1,
  cache_level: null,
  quality_scores: null,
  backtrack_triggered: false,
  backtrack_strategy: null,
}

async function mountDetails(response = makeResponse()) {
  const { default: RetrievalDetails } = await import("../RetrievalDetails.vue")
  return mount(RetrievalDetails, { props: { response } })
}

describe("RetrievalDetails 检索详情收纳", () => {
  // 验证默认折叠：按钮 aria-expanded=false，三个诊断面板都不渲染
  it("默认折叠且不渲染任何诊断面板", async () => {
    const wrapper = await mountDetails(makeResponse({ rewrite_info: rewriteInfo }))

    const toggle = wrapper.find('[data-testid="retrieval-details-toggle"]')
    expect(toggle.element.tagName).toBe("BUTTON")
    expect(toggle.attributes("aria-expanded")).toBe("false")
    expect(wrapper.find('[data-testid="rewrite"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="results"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="prompt"]').exists()).toBe(false)
  })

  // 验证折叠状态也能看到片段数与耗时摘要，用户无需展开就知道检索规模
  it("折叠状态显示片段数和检索耗时摘要", async () => {
    const response = makeResponse({
      search_time_ms: 120,
      results: [1, 2, 3, 4, 5].map((n) => makeResult({ rank: n, chunk_id: `c${n}` })),
    })
    const wrapper = await mountDetails(response)

    const toggle = wrapper.find('[data-testid="retrieval-details-toggle"]')
    expect(toggle.text()).toContain("检索详情")
    expect(toggle.text()).toContain("5 个片段")
    expect(toggle.text()).toContain("120 ms")
  })

  // 验证展开后显示全部可用的诊断面板（改写、检索结果、提示词）
  it("展开后显示改写、检索结果与提示词面板", async () => {
    const wrapper = await mountDetails(makeResponse({ rewrite_info: rewriteInfo }))

    await wrapper.find('[data-testid="retrieval-details-toggle"]').trigger("click")

    expect(wrapper.find('[data-testid="retrieval-details-toggle"]').attributes("aria-expanded")).toBe("true")
    expect(wrapper.find('[data-testid="rewrite"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="results"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="prompt"]').exists()).toBe(true)
  })

  // 验证展开区域与按钮通过 aria-controls 关联
  it("按钮 aria-controls 指向展开区域", async () => {
    const wrapper = await mountDetails()

    const toggle = wrapper.find('[data-testid="retrieval-details-toggle"]')
    await toggle.trigger("click")

    const controls = toggle.attributes("aria-controls")
    expect(controls).toBeTruthy()
    expect(wrapper.find(`#${controls}`).exists()).toBe(true)
  })

  // 验证缺少改写信息和提示词时只显示检索结果面板，不渲染空面板
  it("rewrite_info 为 null 且无提示词时只显示检索结果面板", async () => {
    const wrapper = await mountDetails(makeResponse({ rewrite_info: null, prompt_messages: [] }))

    await wrapper.find('[data-testid="retrieval-details-toggle"]').trigger("click")

    expect(wrapper.find('[data-testid="rewrite"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="prompt"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="results"]').exists()).toBe(true)
  })

  // 验证零结果时不渲染检索结果面板（来源列表已负责提示无依据）
  it("零结果时不渲染检索结果面板", async () => {
    const wrapper = await mountDetails(makeResponse({ results: [] }))

    await wrapper.find('[data-testid="retrieval-details-toggle"]').trigger("click")

    expect(wrapper.find('[data-testid="results"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="retrieval-details-toggle"]').text()).toContain("0 个片段")
  })

  // 验证子面板在展开检索详情后仍保持各自默认折叠（两级收纳，避免信息洪流）
  it("展开后检索结果子面板仍默认折叠", async () => {
    const wrapper = await mountDetails()

    await wrapper.find('[data-testid="retrieval-details-toggle"]').trigger("click")

    expect(wrapper.find('[data-testid="results-content"]').exists()).toBe(false)
  })

  // 验证多轮回答各自的检索详情区域 ID 唯一
  it("两个实例的 aria-controls 互不相同", async () => {
    const a = await mountDetails()
    const b = await mountDetails()

    const idA = a.find('[data-testid="retrieval-details-toggle"]').attributes("aria-controls")
    expect(idA).toBeTruthy()
    expect(idA).not.toBe(b.find('[data-testid="retrieval-details-toggle"]').attributes("aria-controls"))
  })

  // 验证面板头部不出现 button 嵌套 button（提示词面板的复制按钮不能放在折叠按钮内部）
  it("展开提示词面板后不存在嵌套按钮", async () => {
    const wrapper = await mountDetails()

    await wrapper.find('[data-testid="retrieval-details-toggle"]').trigger("click")
    await wrapper.find('[data-testid="prompt-toggle"]').trigger("click")

    expect(wrapper.find('[data-testid="copy-prompt-button"]').exists()).toBe(true)
    expect(wrapper.findAll("button button")).toHaveLength(0)
  })
})
