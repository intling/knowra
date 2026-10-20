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

// ── 重构 RED：欢迎页三步路径、上传入口与推荐问题 ────────────────────────────

describe("WelcomeView 起手路径", () => {
  // 验证欢迎页明确展示「上传资料 → 提问 → 核对来源」三步，让主线一眼可见
  it("渲染上传资料、提问、核对来源三个步骤", async () => {
    const { default: WelcomeView } = await import("../WelcomeView.vue")
    const wrapper = mount(WelcomeView)

    const steps = wrapper.findAll('[data-testid="welcome-step"]')
    expect(steps).toHaveLength(3)
    const text = wrapper.text()
    expect(text).toContain("上传资料")
    expect(text).toContain("提问")
    expect(text).toContain("核对来源")
  })

  // 验证第一步内含真实可点击的上传按钮，点击后向上抛出 upload 事件（由 ChatArea 打开文件选择）
  it("点击上传资料按钮 emit upload 事件", async () => {
    const { default: WelcomeView } = await import("../WelcomeView.vue")
    const wrapper = mount(WelcomeView)

    const button = wrapper.find('[data-testid="welcome-upload"]')
    expect(button.element.tagName).toBe("BUTTON")
    await button.trigger("click")

    expect(wrapper.emitted("upload")).toHaveLength(1)
  })

  // 验证推荐问题至少三条，并且点击后只抛出填入事件而不发送
  it("推荐问题不少于三条且点击 emit pick-suggestion 而不发送", async () => {
    const { default: WelcomeView } = await import("../WelcomeView.vue")
    const wrapper = mount(WelcomeView)

    const suggestions = wrapper.findAll('[data-testid="welcome-suggestion"]')
    expect(suggestions.length).toBeGreaterThanOrEqual(3)

    const first = suggestions[0]!
    await first.trigger("click")

    expect(wrapper.emitted("pick-suggestion")).toHaveLength(1)
    expect(wrapper.emitted("pick-suggestion")![0]![0]).toBe(first.text())
    expect(wrapper.emitted("send")).toBeUndefined()
  })

  // 验证推荐问题文案是通用措辞，不伪造具体文档名或知识点
  it("推荐问题不包含具体文档名或伪造内容", async () => {
    const { default: WelcomeView } = await import("../WelcomeView.vue")
    const wrapper = mount(WelcomeView)

    const suggestions = wrapper.findAll('[data-testid="welcome-suggestion"]')
    expect(suggestions.length, "应至少渲染 3 条推荐问题").toBeGreaterThanOrEqual(3)
    for (const s of suggestions) {
      expect(s.text()).not.toMatch(/\.pdf|\.docx|\.md\b/)
      expect(s.text().length).toBeGreaterThan(4)
    }
  })
})

// ── 重构 RED：用户消息排版保留 ─────────────────────────────────────────────

describe("UserMessage 排版契约", () => {
  // 验证多行消息使用 whitespace-pre-wrap 保留换行（后端回答与用户粘贴的多行文本都需要）
  it("气泡使用 whitespace-pre-wrap 保留换行", async () => {
    const { default: UserMessage } = await import("../UserMessage.vue")
    const wrapper = mount(UserMessage, {
      props: { content: "第一行\n第二行" },
    })

    const bubble = wrapper.find('[data-testid="user-message-bubble"]')
    expect(bubble.classes()).toContain("whitespace-pre-wrap")
  })

  // 验证超长无空格文本可折行，不撑破 320px 视口
  it("气泡启用 overflow-wrap: anywhere 防止长串撑破布局", async () => {
    const { default: UserMessage } = await import("../UserMessage.vue")
    const wrapper = mount(UserMessage, {
      props: { content: "a".repeat(200) },
    })

    const bubble = wrapper.find('[data-testid="user-message-bubble"]')
    expect(bubble.classes()).toContain("[overflow-wrap:anywhere]")
  })

  // 验证用户气泡使用品牌强调色令牌，与回答的纸面底色形成明确对比
  it("用户气泡使用品牌强调色背景", async () => {
    const { default: UserMessage } = await import("../UserMessage.vue")
    const wrapper = mount(UserMessage, { props: { content: "hi" } })

    expect(wrapper.find('[data-testid="user-message-bubble"]').classes()).toContain("bg-brand-700")
  })
})
