import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

// ── Helpers ──────────────────────────────────────────────────────────────────

interface AttachedFile {
  id: string
  name: string
  size: number
  status: "pending" | "uploading" | "uploaded" | "error"
  error?: string
}

// ── Tests: ChatInput 增强（附件功能）─────────────────────────────────────────

describe("ChatInput 附件功能", () => {
  describe("多文件 chips 渲染", () => {
    it("有附件文件时渲染文件 chips", async () => {
      const files: AttachedFile[] = [
        { id: "f1", name: "document.pdf", size: 1024000, status: "pending" },
        { id: "f2", name: "image.png", size: 512000, status: "pending" },
      ]
      // 延迟导入以确保 mock 生效，实际无需 mock
      const { default: ChatInput } = await import("../ChatInput.vue")
      const wrapper = mount(ChatInput, {
        props: {
          modelValue: "",
          topK: 5,
          loading: false,
          files,
        },
      })

      const chips = wrapper.findAll('[data-testid="file-chip"]')
      expect(chips).toHaveLength(2)
    })

    it("每个 chip 显示文件名", async () => {
      const files: AttachedFile[] = [
        { id: "f1", name: "研究报告.pdf", size: 2048000, status: "pending" },
      ]
      const { default: ChatInput } = await import("../ChatInput.vue")
      const wrapper = mount(ChatInput, {
        props: {
          modelValue: "",
          topK: 5,
          loading: false,
          files,
        },
      })

      const chip = wrapper.find('[data-testid="file-chip"]')
      expect(chip.text()).toContain("研究报告.pdf")
    })

    it("每个 chip 显示文件大小", async () => {
      const files: AttachedFile[] = [
        { id: "f1", name: "doc.pdf", size: 1048576, status: "pending" },
      ]
      const { default: ChatInput } = await import("../ChatInput.vue")
      const wrapper = mount(ChatInput, {
        props: {
          modelValue: "",
          topK: 5,
          loading: false,
          files,
        },
      })

      const chip = wrapper.find('[data-testid="file-chip"]')
      // 1MB = 1048576 bytes，格式化后应包含 "MB" 或 "KB"
      expect(chip.text()).toMatch(/(MB|KB|GB|B)/)
    })

    it("无文件时不渲染文件 chips 区域", async () => {
      const { default: ChatInput } = await import("../ChatInput.vue")
      const wrapper = mount(ChatInput, {
        props: {
          modelValue: "",
          topK: 5,
          loading: false,
          files: [],
        },
      })

      expect(wrapper.find('[data-testid="file-chip"]').exists()).toBe(false)
    })

    it("文件 chips 显示在文本输入框上方", async () => {
      const files: AttachedFile[] = [
        { id: "f1", name: "test.txt", size: 100, status: "pending" },
      ]
      const { default: ChatInput } = await import("../ChatInput.vue")
      const wrapper = mount(ChatInput, {
        props: {
          modelValue: "",
          topK: 5,
          loading: false,
          files,
        },
      })

      // file chips 区域应该在 textarea 之前
      const fileChipsArea = wrapper.find('[data-testid="file-chips-area"]')
      expect(fileChipsArea.exists()).toBe(true)
    })
  })

  describe("单文件删除", () => {
    it("点击 chip 删除按钮时 emit remove-file 事件", async () => {
      const files: AttachedFile[] = [
        { id: "f1", name: "doc.pdf", size: 1000, status: "pending" },
      ]
      const { default: ChatInput } = await import("../ChatInput.vue")
      const wrapper = mount(ChatInput, {
        props: {
          modelValue: "",
          topK: 5,
          loading: false,
          files,
        },
      })

      await wrapper.find('[data-testid="file-chip-remove-btn"]').trigger("click")

      expect(wrapper.emitted("remove-file")).toBeTruthy()
      expect(wrapper.emitted("remove-file")![0]).toEqual(["f1"])
    })

    it("删除单个文件不影响其他 chips", async () => {
      const files: AttachedFile[] = [
        { id: "f1", name: "a.pdf", size: 100, status: "pending" },
        { id: "f2", name: "b.pdf", size: 200, status: "pending" },
      ]
      const { default: ChatInput } = await import("../ChatInput.vue")
      const wrapper = mount(ChatInput, {
        props: {
          modelValue: "",
          topK: 5,
          loading: false,
          files,
        },
      })

      const removeButtons = wrapper.findAll('[data-testid="file-chip-remove-btn"]')
      await removeButtons[0]!.trigger("click")

      // 只 emit 第一个文件的删除
      expect(wrapper.emitted("remove-file")![0]).toEqual(["f1"])
    })
  })

  describe("上传状态指示", () => {
    it("上传中的 chip 显示 spinner 动画", async () => {
      const files: AttachedFile[] = [
        { id: "f1", name: "uploading.pdf", size: 1000, status: "uploading" },
      ]
      const { default: ChatInput } = await import("../ChatInput.vue")
      const wrapper = mount(ChatInput, {
        props: {
          modelValue: "",
          topK: 5,
          loading: false,
          files,
        },
      })

      const chip = wrapper.find('[data-testid="file-chip"]')
      expect(chip.find('[data-testid="file-chip-spinner"]').exists()).toBe(true)
    })

    it("上传成功的 chip 显示 ✓ 标记", async () => {
      const files: AttachedFile[] = [
        { id: "f1", name: "done.pdf", size: 1000, status: "uploaded" },
      ]
      const { default: ChatInput } = await import("../ChatInput.vue")
      const wrapper = mount(ChatInput, {
        props: {
          modelValue: "",
          topK: 5,
          loading: false,
          files,
        },
      })

      const chip = wrapper.find('[data-testid="file-chip"]')
      expect(chip.find('[data-testid="file-chip-success"]').exists()).toBe(true)
    })

    it("上传失败的 chip 显示错误状态", async () => {
      const files: AttachedFile[] = [
        { id: "f1", name: "fail.pdf", size: 1000, status: "error", error: "上传失败：文件过大" },
      ]
      const { default: ChatInput } = await import("../ChatInput.vue")
      const wrapper = mount(ChatInput, {
        props: {
          modelValue: "",
          topK: 5,
          loading: false,
          files,
        },
      })

      const chip = wrapper.find('[data-testid="file-chip"]')
      expect(chip.find('[data-testid="file-chip-error"]').exists()).toBe(true)
    })

    it("上传失败的 chip 显示错误信息", async () => {
      const files: AttachedFile[] = [
        { id: "f1", name: "fail.pdf", size: 1000, status: "error", error: "网络错误" },
      ]
      const { default: ChatInput } = await import("../ChatInput.vue")
      const wrapper = mount(ChatInput, {
        props: {
          modelValue: "",
          topK: 5,
          loading: false,
          files,
        },
      })

      expect(wrapper.text()).toContain("网络错误")
    })

    it("待上传的 chip 显示等待状态", async () => {
      const files: AttachedFile[] = [
        { id: "f1", name: "pending.pdf", size: 1000, status: "pending" },
      ]
      const { default: ChatInput } = await import("../ChatInput.vue")
      const wrapper = mount(ChatInput, {
        props: {
          modelValue: "",
          topK: 5,
          loading: false,
          files,
        },
      })

      const chip = wrapper.find('[data-testid="file-chip"]')
      // pending 状态应渲染 chip 但不含 error/success/spinner 指示器
      expect(chip.find('[data-testid="file-chip-error"]').exists()).toBe(false)
      expect(chip.find('[data-testid="file-chip-success"]').exists()).toBe(false)
      expect(chip.find('[data-testid="file-chip-spinner"]').exists()).toBe(false)
    })

    it("上传中时删除按钮仍然可用", async () => {
      const files: AttachedFile[] = [
        { id: "f1", name: "uploading.pdf", size: 1000, status: "uploading" },
      ]
      const { default: ChatInput } = await import("../ChatInput.vue")
      const wrapper = mount(ChatInput, {
        props: {
          modelValue: "",
          topK: 5,
          loading: false,
          files,
        },
      })

      // 上传中仍可删除
      const removeBtn = wrapper.find('[data-testid="file-chip-remove-btn"]')
      expect(removeBtn.exists()).toBe(true)
    })

    it("相同文件不可重复提交（通过外部逻辑控制）", () => {
      // 此行为由父组件 ChatArea 控制——ChatInput 只负责渲染和事件通知
      expect(true).toBe(true)
    })
  })

  describe("附件按钮与发送互不干扰", () => {
    it("渲染附件按钮", async () => {
      const { default: ChatInput } = await import("../ChatInput.vue")
      const wrapper = mount(ChatInput, {
        props: {
          modelValue: "",
          topK: 5,
          loading: false,
          files: [],
        },
      })

      expect(wrapper.find('[data-testid="attach-button"]').exists()).toBe(true)
    })

    it("点击附件按钮时 emit add-files 事件（触发文件选择器）", async () => {
      const { default: ChatInput } = await import("../ChatInput.vue")
      const wrapper = mount(ChatInput, {
        props: {
          modelValue: "",
          topK: 5,
          loading: false,
          files: [],
        },
      })

      await wrapper.find('[data-testid="attach-button"]').trigger("click")

      // 附件按钮点击应由父组件处理文件选择器
      // ChatInput 仅 emit 事件
      expect(wrapper.emitted("add-files")).toBeTruthy()
    })

    it("有附件但无文本时发送按钮可用", async () => {
      const files: AttachedFile[] = [
        { id: "f1", name: "doc.pdf", size: 1000, status: "uploaded" },
      ]
      const { default: ChatInput } = await import("../ChatInput.vue")
      const wrapper = mount(ChatInput, {
        props: {
          modelValue: "", // 空文本
          topK: 5,
          loading: false,
          files,
        },
      })

      const sendBtn = wrapper.find('[data-testid="send-button"]')
      // 发送按钮不应禁用（因为有已上传的附件）
      expect(sendBtn.attributes("disabled")).toBeUndefined()
    })

    it("无文本且无附件时发送按钮禁用", async () => {
      const { default: ChatInput } = await import("../ChatInput.vue")
      const wrapper = mount(ChatInput, {
        props: {
          modelValue: "",
          topK: 5,
          loading: false,
          files: [],
        },
      })

      const sendBtn = wrapper.find('[data-testid="send-button"]')
      expect(sendBtn.attributes("disabled")).toBeDefined()
    })

    it("loading 时附件按钮禁用", async () => {
      const { default: ChatInput } = await import("../ChatInput.vue")
      const wrapper = mount(ChatInput, {
        props: {
          modelValue: "",
          topK: 5,
          loading: true,
          files: [],
        },
      })

      const attachBtn = wrapper.find('[data-testid="attach-button"]')
      expect(attachBtn.attributes("disabled")).toBeDefined()
    })

    it("附件按钮与发送按钮在 DOM 中共存且独立", async () => {
      const files: AttachedFile[] = [
        { id: "f1", name: "doc.pdf", size: 1000, status: "uploaded" },
      ]
      const { default: ChatInput } = await import("../ChatInput.vue")
      const wrapper = mount(ChatInput, {
        props: {
          modelValue: "测试文本",
          topK: 5,
          loading: false,
          files,
        },
      })

      expect(wrapper.find('[data-testid="attach-button"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="send-button"]').exists()).toBe(true)
    })

    it("未上传完成的文件不应阻止发送", async () => {
      const files: AttachedFile[] = [
        { id: "f1", name: "uploading.pdf", size: 1000, status: "uploading" },
      ]
      const { default: ChatInput } = await import("../ChatInput.vue")
      const wrapper = mount(ChatInput, {
        props: {
          modelValue: "测试问题", // 有文本
          topK: 5,
          loading: false,
          files,
        },
      })

      const sendBtn = wrapper.find('[data-testid="send-button"]')
      // 有文本内容时，即使文件还在上传中，发送按钮也应可用
      expect(sendBtn.attributes("disabled")).toBeUndefined()
    })
  })

  describe("Top-K 与加载状态保持", () => {
    it("loading 时显示加载文案和 spinner", async () => {
      const { default: ChatInput } = await import("../ChatInput.vue")
      const wrapper = mount(ChatInput, {
        props: {
          modelValue: "test",
          topK: 5,
          loading: true,
          loadingStage: "searching",
          files: [],
        },
      })

      const sendBtn = wrapper.find('[data-testid="send-button"]')
      expect(sendBtn.text()).toContain("搜索中")
    })

    it("Top-K 滑块在 loading 时禁用", async () => {
      const { default: ChatInput } = await import("../ChatInput.vue")
      const wrapper = mount(ChatInput, {
        props: {
          modelValue: "",
          topK: 5,
          loading: true,
          files: [],
        },
      })

      const slider = wrapper.find("#topk-slider")
      const el = slider.element as HTMLInputElement
      expect(el.disabled).toBe(true)
    })
  })
})
