import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import AnswerPanel from "../AnswerPanel.vue"

const tokens = { prompt_tokens: 500, completion_tokens: 200, total_tokens: 700 }

describe("AnswerPanel 回答底栏", () => {
  // 验证 Token 底栏只显示总数，不再把 prompt/completion 明细常显在底栏
  it("Token 统计可见文本只显示总数", () => {
    const wrapper = mount(AnswerPanel, {
      props: { answer: "回答", answerTokens: tokens, totalResults: 2, documentCount: 1 },
    })

    const stats = wrapper.find('[data-testid="token-stats"]')
    const visible = stats.find('[data-testid="token-total"]')
    expect(visible.exists(), "token-stats 内应有仅含总数的可见元素 token-total（明细放在 title / sr-only）").toBe(true)
    expect(visible.text()).toContain("700")
    expect(visible.text()).toContain("tokens")
    expect(visible.text()).not.toContain("prompt")
    expect(visible.text()).not.toContain("completion")
  })

  // 验证明细通过悬停提示提供，信息不丢失
  it("Token 明细出现在 title 悬停提示中", () => {
    const wrapper = mount(AnswerPanel, {
      props: { answer: "回答", answerTokens: tokens },
    })

    const title = wrapper.find('[data-testid="token-stats"]').attributes("title") ?? ""
    expect(title).toContain("500")
    expect(title).toContain("200")
  })

  // 验证引用统计文案保持兼容（引用 N 个分块 · 来自 K 个文档），由调用方传入去重后的文档数
  it("引用统计显示分块数与文档数", () => {
    const wrapper = mount(AnswerPanel, {
      props: { answer: "回答", totalResults: 2, documentCount: 1 },
    })

    expect(wrapper.find('[data-testid="citation-stats"]').text()).toContain("引用 2 个分块")
    expect(wrapper.find('[data-testid="citation-stats"]').text()).toContain("来自 1 个文档")
  })

  // 验证 Markdown 有序/无序列表被渲染为真实列表元素（CSS 列表标记由样式契约测试保证）
  it("Markdown 列表渲染为 ol / ul 元素", () => {
    const wrapper = mount(AnswerPanel, {
      props: { answer: "1. 第一步\n2. 第二步\n\n- 要点甲\n- 要点乙" },
    })

    const content = wrapper.find('[data-testid="answer-content"]')
    expect(content.findAll("ol > li")).toHaveLength(2)
    expect(content.findAll("ul > li")).toHaveLength(2)
  })

  // 验证回答正文只使用 prose-knowra，不再挂无效的 typography 插件类名
  it("回答正文使用 prose-knowra 且不含无效的 prose 类", () => {
    const wrapper = mount(AnswerPanel, { props: { answer: "正文" } })

    const classes = wrapper.find('[data-testid="answer-content"]').classes()
    expect(classes).toContain("prose-knowra")
    expect(classes).not.toContain("prose")
    expect(classes).not.toContain("prose-sm")
  })
})
