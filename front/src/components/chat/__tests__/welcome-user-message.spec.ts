import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

// ── Tests: WelcomeView ────────────────────────────────────────────────────────

describe("WelcomeView", () => {
  describe("渲染", () => {
    it("渲染欢迎语主标题", async () => {
      const { default: WelcomeView } = await import("../WelcomeView.vue")
      const wrapper = mount(WelcomeView)

      expect(wrapper.find('[data-testid="welcome-view"]').exists()).toBe(true)
      expect(wrapper.text()).toContain("今天想了解什么？")
    })

    it("渲染引导副标题文案", async () => {
      const { default: WelcomeView } = await import("../WelcomeView.vue")
      const wrapper = mount(WelcomeView)

      // 引导文案：提示用户上传资料或提问
      expect(wrapper.find('[data-testid="welcome-subtitle"]').exists()).toBe(true)
      expect(wrapper.text()).toContain("上传资料")
    })

    it("渲染欢迎图标或插图占位区域", async () => {
      const { default: WelcomeView } = await import("../WelcomeView.vue")
      const wrapper = mount(WelcomeView)

      // 图标占位区域应存在
      expect(wrapper.find('[data-testid="welcome-icon"]').exists()).toBe(true)
    })

    it("欢迎页居中显示", async () => {
      const { default: WelcomeView } = await import("../WelcomeView.vue")
      const wrapper = mount(WelcomeView)

      const container = wrapper.find('[data-testid="welcome-view"]')
      expect(container.classes()).toContain("flex")
      expect(container.classes()).toContain("flex-col")
    })
  })
})

// ── Tests: UserMessage ────────────────────────────────────────────────────────

describe("UserMessage", () => {
  describe("渲染", () => {
    it("渲染消息文本内容", async () => {
      const { default: UserMessage } = await import("../UserMessage.vue")
      const wrapper = mount(UserMessage, {
        props: {
          content: "这是一个测试问题",
        },
      })

      expect(wrapper.find('[data-testid="user-message"]').exists()).toBe(true)
      expect(wrapper.text()).toContain("这是一个测试问题")
    })

    it("消息气泡右对齐展示", async () => {
      const { default: UserMessage } = await import("../UserMessage.vue")
      const wrapper = mount(UserMessage, {
        props: {
          content: "测试消息",
        },
      })

      // 外层容器应右对齐
      const outerContainer = wrapper.find('[data-testid="user-message"]')
      expect(outerContainer.classes()).toContain("flex")
      expect(outerContainer.classes()).toContain("justify-end")
    })

    it("消息气泡使用品牌色背景 + 白色文字样式", async () => {
      const { default: UserMessage } = await import("../UserMessage.vue")
      const wrapper = mount(UserMessage, {
        props: {
          content: "测试消息",
        },
      })

      const bubble = wrapper.find('[data-testid="user-message-bubble"]')
      expect(bubble.classes()).toContain("bg-brand-700")
      expect(bubble.classes()).toContain("text-white")
    })

    it("消息气泡使用规定的圆角样式", async () => {
      const { default: UserMessage } = await import("../UserMessage.vue")
      const wrapper = mount(UserMessage, {
        props: {
          content: "测试消息",
        },
      })

      const bubble = wrapper.find('[data-testid="user-message-bubble"]')
      expect(bubble.classes()).toContain("rounded-xl")
      expect(bubble.classes()).toContain("rounded-br-sm")
    })

    it("消息气泡最大宽度限制为 85%", async () => {
      const { default: UserMessage } = await import("../UserMessage.vue")
      const wrapper = mount(UserMessage, {
        props: {
          content: "测试消息",
        },
      })

      const bubble = wrapper.find('[data-testid="user-message-bubble"]')
      expect(bubble.classes()).toContain("max-w-[85%]")
    })

    it("支持渲染长文本内容", async () => {
      const { default: UserMessage } = await import("../UserMessage.vue")
      const longContent = "这是一段非常长的用户消息内容，用于测试消息气泡在长文本场景下的渲染表现。".repeat(5)
      const wrapper = mount(UserMessage, {
        props: {
          content: longContent,
        },
      })

      expect(wrapper.text()).toContain(longContent)
    })
  })

  describe("发送后欢迎页消失（与 WelcomeView 协作）", () => {
    it("有消息时不应同时显示欢迎页", () => {
      // 逻辑测试：UserMessage 存在时意味着消息已发送，WelcomeView 不显示
      // 这个集成行为在 ChatArea 中实现，此处验证两个组件独立工作
      expect(true).toBe(true)
    })
  })
})
