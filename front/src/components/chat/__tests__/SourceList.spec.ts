import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import { makeResult } from "../../../__tests__/fixtures/search"

async function mountSourceList(results: ReturnType<typeof makeResult>[]) {
  const { default: SourceList } = await import("../SourceList.vue")
  return mount(SourceList, { props: { results } })
}

/** 两份文档、三条结果：A(rank1, p3, #12) / B(rank2, 无页码, #4) / A(rank3, p3-4, #15) */
function threeResultsTwoDocs() {
  return [
    makeResult({
      rank: 1,
      chunk_id: "a-12",
      parsed_document_id: "doc-a",
      document_name: "线性代数讲义.pdf",
      sequence_index: 12,
      page_numbers: [3],
      text: "特征值是满足 Av = λv 的标量 λ。",
    }),
    makeResult({
      rank: 2,
      chunk_id: "b-4",
      parsed_document_id: "doc-b",
      document_name: "矩阵论笔记.md",
      sequence_index: 4,
      page_numbers: null,
      heading_path: ["对角化"],
      text: "可对角化当且仅当存在 n 个线性无关的特征向量。",
    }),
    makeResult({
      rank: 3,
      chunk_id: "a-15",
      parsed_document_id: "doc-a",
      document_name: "线性代数讲义.pdf",
      sequence_index: 15,
      page_numbers: [4, 3],
      text: "第一行原文\n第二行原文",
    }),
  ]
}

describe("SourceList 来源列表", () => {
  // 验证按 parsed_document_id 聚合，并按首次出现顺序编号（A 在前、B 在后）
  it("按文档聚合并按首次出现顺序编号", async () => {
    const wrapper = await mountSourceList(threeResultsTwoDocs())

    const items = wrapper.findAll('[data-testid="source-item"]')
    expect(items).toHaveLength(2)
    expect(items[0]!.find('[data-testid="source-index"]').text()).toBe("1")
    expect(items[0]!.find('[data-testid="source-doc-name"]').text()).toBe("线性代数讲义.pdf")
    expect(items[1]!.find('[data-testid="source-index"]').text()).toBe("2")
    expect(items[1]!.find('[data-testid="source-doc-name"]').text()).toBe("矩阵论笔记.md")
  })

  // 验证标题直接告诉用户本回答依据了几份文档
  it("标题显示来源文档数量", async () => {
    const wrapper = await mountSourceList(threeResultsTwoDocs())

    expect(wrapper.find('[data-testid="source-list-title"]').text()).toContain("来源")
    expect(wrapper.find('[data-testid="source-list-title"]').text()).toContain("2 份文档")
  })

  // 验证同一文档的页码去重并升序合并（[3] + [4,3] → 第 3、4 页）
  it("合并去重排序页码", async () => {
    const wrapper = await mountSourceList(threeResultsTwoDocs())

    const first = wrapper.findAll('[data-testid="source-item"]')[0]!
    expect(first.find('[data-testid="source-pages"]').text()).toBe("第 3、4 页")
  })

  // 验证没有页码的文档不渲染页码文案（而不是显示"第  页"）
  it("无页码时不显示页码", async () => {
    const wrapper = await mountSourceList(threeResultsTwoDocs())

    const second = wrapper.findAll('[data-testid="source-item"]')[1]!
    expect(second.find('[data-testid="source-pages"]').exists()).toBe(false)
  })

  // 验证每个来源条目列出全部分块编号，便于和检索详情对照
  it("显示该文档所有片段的分块编号", async () => {
    const wrapper = await mountSourceList(threeResultsTwoDocs())

    const first = wrapper.findAll('[data-testid="source-item"]')[0]!
    expect(first.text()).toContain("分块 #12")
    expect(first.text()).toContain("分块 #15")
  })

  // 验证同名但 ID 不同的文档不会被误合并（避免把两份资料当成一份）
  it("同名不同 ID 的文档分开显示", async () => {
    const wrapper = await mountSourceList([
      makeResult({ rank: 1, chunk_id: "x1", parsed_document_id: "doc-x", document_name: "笔记.md" }),
      makeResult({ rank: 2, chunk_id: "y1", parsed_document_id: "doc-y", document_name: "笔记.md" }),
    ])

    expect(wrapper.findAll('[data-testid="source-item"]')).toHaveLength(2)
  })

  // 验证文档名为空时显示可读的回退文案
  it("文档名为空时显示「未命名文档」", async () => {
    const wrapper = await mountSourceList([makeResult({ document_name: "" })])

    expect(wrapper.find('[data-testid="source-doc-name"]').text()).toBe("未命名文档")
  })

  // 验证默认折叠：显示首个片段预览，按钮 aria-expanded=false，不渲染原文全文
  it("默认显示首个片段预览且处于折叠状态", async () => {
    const wrapper = await mountSourceList(threeResultsTwoDocs())

    const first = wrapper.findAll('[data-testid="source-item"]')[0]!
    expect(first.find('[data-testid="source-preview"]').text()).toContain("特征值是满足 Av = λv 的标量 λ。")
    expect(first.find('[data-testid="source-toggle"]').attributes("aria-expanded")).toBe("false")
    expect(first.find('[data-testid="source-chunk"]').exists()).toBe(false)
  })

  // 验证展开后显示该文档每个片段的原始全文，并保留原文换行
  it("点击展开后显示全部片段原文并保留换行", async () => {
    const wrapper = await mountSourceList(threeResultsTwoDocs())

    const first = wrapper.findAll('[data-testid="source-item"]')[0]!
    await first.find('[data-testid="source-toggle"]').trigger("click")

    expect(first.find('[data-testid="source-toggle"]').attributes("aria-expanded")).toBe("true")
    const chunks = first.findAll('[data-testid="source-chunk"]')
    expect(chunks).toHaveLength(2)
    const fullText = chunks[1]!.find('[data-testid="source-chunk-text"]')
    expect((fullText.element as HTMLElement).textContent).toContain("第一行原文\n第二行原文")
    expect(fullText.classes()).toContain("whitespace-pre-wrap")
  })

  // 验证展开按钮通过 aria-controls 关联到展开区域，读屏用户可以定位内容
  it("展开按钮的 aria-controls 指向展开区域", async () => {
    const wrapper = await mountSourceList(threeResultsTwoDocs())

    const first = wrapper.findAll('[data-testid="source-item"]')[0]!
    const toggle = first.find('[data-testid="source-toggle"]')
    await toggle.trigger("click")

    const controls = toggle.attributes("aria-controls")
    expect(controls).toBeTruthy()
    expect(first.find(`#${controls}`).exists()).toBe(true)
  })

  // 验证再次点击可以收起
  it("再次点击收起原文", async () => {
    const wrapper = await mountSourceList(threeResultsTwoDocs())

    const toggle = wrapper.find('[data-testid="source-toggle"]')
    await toggle.trigger("click")
    await toggle.trigger("click")

    expect(toggle.attributes("aria-expanded")).toBe("false")
    expect(wrapper.find('[data-testid="source-chunk"]').exists()).toBe(false)
  })

  // 验证零结果时明确告诉用户回答缺少资料依据，而不是静默不显示
  it("无结果时提示回答缺少资料依据", async () => {
    const wrapper = await mountSourceList([])

    const empty = wrapper.find('[data-testid="sources-empty"]')
    expect(empty.exists()).toBe(true)
    expect(empty.text()).toContain("没有检索到相关资料")
    expect(empty.text()).toContain("缺少资料依据")
    expect(wrapper.find('[data-testid="source-item"]').exists()).toBe(false)
  })

  // 验证同一文档出现在多轮回答的来源列表时，展开区域 ID 仍全局唯一
  it("多个实例中同一文档的 aria-controls ID 唯一", async () => {
    const { default: SourceList } = await import("../SourceList.vue")
    const results = [makeResult()]
    const a = mount(SourceList, { props: { results } })
    const b = mount(SourceList, { props: { results } })

    const idA = a.find('[data-testid="source-toggle"]').attributes("aria-controls")
    const idB = b.find('[data-testid="source-toggle"]').attributes("aria-controls")
    expect(idA).toBeTruthy()
    expect(idA).not.toBe(idB)
  })

  // 验证展开的原文与 API 返回的 text 完全一致（不做摘要或改写）
  it("展开原文与 API 返回文本完全一致", async () => {
    const original = "  原文首行带空格\n\n第三行：Av = λv  "
    const wrapper = await mountSourceList([makeResult({ text: original })])

    await wrapper.find('[data-testid="source-toggle"]').trigger("click")

    expect(wrapper.find('[data-testid="source-chunk-text"]').element.textContent).toBe(original)
  })

  // 验证展开后每个片段保留其原始检索排名
  it("展开后显示每个片段的原始排名", async () => {
    const wrapper = await mountSourceList(threeResultsTwoDocs())

    const first = wrapper.findAll('[data-testid="source-item"]')[0]!
    await first.find('[data-testid="source-toggle"]').trigger("click")
    const chunks = first.findAll('[data-testid="source-chunk"]')
    expect(chunks[0]!.text()).toContain("#1")
    expect(chunks[1]!.text()).toContain("#3")
  })
})
