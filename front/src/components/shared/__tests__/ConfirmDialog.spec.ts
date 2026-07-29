import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import ConfirmDialog from "../ConfirmDialog.vue"

// ── Tests: ConfirmDialog ─────────────────────────────────────────────────────

describe("ConfirmDialog", () => {
  describe("渲染", () => {
    it("默认不可见（v-if false 时不渲染）", () => {
      const wrapper = mount(ConfirmDialog, {
        props: {
          visible: false,
          title: "确认删除",
          message: "确定要删除吗？",
        },
      })

      // 当 visible=false 时，DOM 中不应有 dialog 结构
      expect(wrapper.find('[data-testid="confirm-dialog-overlay"]').exists()).toBe(false)
    })

    it("visible=true 时渲染对话框", () => {
      const wrapper = mount(ConfirmDialog, {
        props: {
          visible: true,
          title: "确认删除",
          message: "确定要删除吗？",
        },
      })

      expect(wrapper.find('[data-testid="confirm-dialog-overlay"]').exists()).toBe(true)
    })

    it("渲染标题", () => {
      const wrapper = mount(ConfirmDialog, {
        props: {
          visible: true,
          title: "确认删除",
          message: "确定要删除吗？",
        },
      })

      expect(wrapper.text()).toContain("确认删除")
    })

    it("渲染消息内容", () => {
      const wrapper = mount(ConfirmDialog, {
        props: {
          visible: true,
          title: "确认操作",
          message: "此操作不可撤销",
        },
      })

      expect(wrapper.text()).toContain("此操作不可撤销")
    })
  })

  describe("确认/取消交互", () => {
    it("点击确认按钮时 emit confirm 事件", async () => {
      const wrapper = mount(ConfirmDialog, {
        props: {
          visible: true,
          title: "确认删除",
          message: "确定要删除吗？",
        },
      })

      await wrapper.find('[data-testid="confirm-dialog-confirm-btn"]').trigger("click")

      expect(wrapper.emitted("confirm")).toBeTruthy()
      expect(wrapper.emitted("confirm")).toHaveLength(1)
    })

    it("点击取消按钮时 emit cancel 事件", async () => {
      const wrapper = mount(ConfirmDialog, {
        props: {
          visible: true,
          title: "确认删除",
          message: "确定要删除吗？",
        },
      })

      await wrapper.find('[data-testid="confirm-dialog-cancel-btn"]').trigger("click")

      expect(wrapper.emitted("cancel")).toBeTruthy()
      expect(wrapper.emitted("cancel")).toHaveLength(1)
    })

    it("点击遮罩层时 emit cancel 事件", async () => {
      const wrapper = mount(ConfirmDialog, {
        props: {
          visible: true,
          title: "确认删除",
          message: "确定要删除吗？",
        },
      })

      await wrapper.find('[data-testid="confirm-dialog-overlay"]').trigger("click")

      expect(wrapper.emitted("cancel")).toBeTruthy()
    })
  })

  describe("插槽内容渲染", () => {
    it("默认插槽内容渲染在对话框中", () => {
      const wrapper = mount(ConfirmDialog, {
        props: {
          visible: true,
          title: "确认操作",
        },
        slots: {
          default: '<p data-testid="custom-slot-content">自定义内容区域</p>',
        },
      })

      expect(wrapper.find('[data-testid="custom-slot-content"]').exists()).toBe(true)
      expect(wrapper.text()).toContain("自定义内容区域")
    })

    it("有插槽内容时 message prop 可被覆盖", () => {
      const wrapper = mount(ConfirmDialog, {
        props: {
          visible: true,
          title: "确认操作",
          message: "默认消息",
        },
        slots: {
          default: '<p data-testid="custom-slot-content">插槽自定义消息</p>',
        },
      })

      // 插槽内容应渲染
      expect(wrapper.find('[data-testid="custom-slot-content"]').exists()).toBe(true)
      // 当有插槽时，插槽内容替代 message
      expect(wrapper.text()).toContain("插槽自定义消息")
    })

    it("确认按钮文字可通过 confirmText prop 自定义", () => {
      const wrapper = mount(ConfirmDialog, {
        props: {
          visible: true,
          title: "确认操作",
          message: "确定吗？",
          confirmText: "是的，删除",
        },
      })

      const btn = wrapper.find('[data-testid="confirm-dialog-confirm-btn"]')
      expect(btn.text()).toContain("是的，删除")
    })

    it("取消按钮文字可通过 cancelText prop 自定义", () => {
      const wrapper = mount(ConfirmDialog, {
        props: {
          visible: true,
          title: "确认操作",
          message: "确定吗？",
          cancelText: "我再想想",
        },
      })

      const btn = wrapper.find('[data-testid="confirm-dialog-cancel-btn"]')
      expect(btn.text()).toContain("我再想想")
    })

    it("默认确认按钮文字为'确认'", () => {
      const wrapper = mount(ConfirmDialog, {
        props: {
          visible: true,
          title: "确认操作",
          message: "确定吗？",
        },
      })

      const btn = wrapper.find('[data-testid="confirm-dialog-confirm-btn"]')
      expect(btn.text()).toContain("确认")
    })

    it("默认取消按钮文字为'取消'", () => {
      const wrapper = mount(ConfirmDialog, {
        props: {
          visible: true,
          title: "确认操作",
          message: "确定吗？",
        },
      })

      const btn = wrapper.find('[data-testid="confirm-dialog-cancel-btn"]')
      expect(btn.text()).toContain("取消")
    })
  })

  describe("危险模式", () => {
    it("danger=true 时确认按钮使用红色样式", () => {
      const wrapper = mount(ConfirmDialog, {
        props: {
          visible: true,
          title: "确认删除",
          message: "此操作不可撤销",
          danger: true,
        },
      })

      const btn = wrapper.find('[data-testid="confirm-dialog-confirm-btn"]')
      expect(btn.classes()).toContain("bg-red-600")
    })

    it("danger=false 时确认按钮使用品牌蓝样式", () => {
      const wrapper = mount(ConfirmDialog, {
        props: {
          visible: true,
          title: "确认操作",
          message: "确定吗？",
          danger: false,
        },
      })

      const btn = wrapper.find('[data-testid="confirm-dialog-confirm-btn"]')
      expect(btn.classes()).toContain("bg-brand-700")
    })
  })
})
