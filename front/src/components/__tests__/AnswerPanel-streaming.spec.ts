import { flushPromises, mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import AnswerPanel from "../AnswerPanel.vue"

describe("AnswerPanel 生成反馈", () => {
  // 验证生成态有独立读屏状态与装饰光标，不把每个 token 当作整段 live 消息反复播报。
  it("生成时显示可访问状态与装饰光标，结束后移除", async () => {
    const props = { answer: "第一段正文", streaming: true, answerTokens: null }
    const wrapper = mount(AnswerPanel, { props })
    try {
      const panel = wrapper.find('[data-testid="answer-panel"]')
      expect(panel.attributes("aria-busy")).toBe("true")
      const cursor = wrapper.find('[data-testid="streaming-cursor"]')
      expect(cursor.exists()).toBe(true)
      expect(cursor.attributes("aria-hidden")).toBe("true")
      expect(wrapper.find('[data-testid="streaming-status"]').attributes("role")).toBe("status")
      expect(wrapper.find('[data-testid="answer-content"]').attributes("aria-live")).not.toBe("assertive")
      expect(wrapper.find('[data-testid="token-stats"]').exists()).toBe(false)
      await wrapper.setProps({ streaming: false })
      await flushPromises()
      expect(wrapper.find('[data-testid="streaming-cursor"]').exists()).toBe(false)
      expect(wrapper.find('[data-testid="answer-panel"]').attributes("aria-busy")).not.toBe("true")
      expect(wrapper.find('[data-testid="answer-content"]').text()).toBe("第一段正文")
    } finally {
      wrapper.unmount()
    }
  })

  // 回归守护：每次增量 Markdown 都经过原有净化，未闭合标记不能引入可执行 HTML。
  it("增量 Markdown 持续净化且正确闭合代码与强调", async () => {
    const props = { answer: "**特征", streaming: true }
    const wrapper = mount(AnswerPanel, { props })
    try {
      await wrapper.setProps({ answer: '**特征值**\n\n<img src=x onerror="alert(1)">\n\n```js\nconst n = 1;' })
      await flushPromises()
      const content = wrapper.find('[data-testid="answer-content"]')
      expect(content.find("strong").text()).toBe("特征值")
      expect(content.html()).not.toContain("onerror")
      await wrapper.setProps({ answer: "**特征值**\n\n```js\nconst n = 1;\n```", streaming: false })
      await flushPromises()
      expect(wrapper.findAll('[data-testid="answer-content"] pre')).toHaveLength(1)
      expect(wrapper.findAll(".code-copy-btn")).toHaveLength(1)
      expect(wrapper.find('[data-testid="answer-content"]').text()).toContain("const n = 1;")
    } finally {
      wrapper.unmount()
    }
  })
})
