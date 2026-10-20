import { enableAutoUnmount, mount } from "@vue/test-utils"
import { afterEach, describe, expect, it } from "vitest"

import ConfirmDialog from "../ConfirmDialog.vue"

// 每个用例结束后卸载，避免已打开对话框的全局键盘监听泄漏到后续用例
enableAutoUnmount(afterEach)

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

// ── 重构 RED：确认框可访问性与键盘行为 ─────────────────────────────────────

describe("ConfirmDialog 可访问性", () => {
  // 验证对话框具备模态语义，并通过 aria-labelledby 关联标题
  it("具备 role=dialog、aria-modal 与 aria-labelledby", () => {
    const wrapper = mount(ConfirmDialog, {
      props: { visible: true, title: "删除这段对话？" },
    })

    const dialog = wrapper.find('[role="dialog"]')
    expect(dialog.exists()).toBe(true)
    expect(dialog.attributes("aria-modal")).toBe("true")
    const labelledby = dialog.attributes("aria-labelledby")
    expect(labelledby).toBeTruthy()
    expect(wrapper.find(`#${labelledby}`).text()).toBe("删除这段对话？")
  })

  // 验证打开后焦点落在「取消」上（危险操作的安全默认）
  it("打开时焦点落在取消按钮", async () => {
    const wrapper = mount(ConfirmDialog, {
      props: { visible: false, title: "删除这段对话？" },
      attachTo: document.body,
    })
    await wrapper.setProps({ visible: true })
    await wrapper.vm.$nextTick()

    expect(document.activeElement).toBe(
      wrapper.find('[data-testid="confirm-dialog-cancel-btn"]').element,
    )
    wrapper.unmount()
  })

  // 验证按 Esc 触发取消
  it("按 Esc emit cancel", async () => {
    const wrapper = mount(ConfirmDialog, {
      props: { visible: true, title: "删除这段对话？" },
      attachTo: document.body,
    })

    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))

    expect(wrapper.emitted("cancel")).toHaveLength(1)
    expect(wrapper.emitted("confirm")).toBeUndefined()
    wrapper.unmount()
  })

  // 验证对话框不可见时 Esc 不会误触发取消
  it("不可见时按 Esc 不 emit cancel", async () => {
    const wrapper = mount(ConfirmDialog, {
      props: { visible: false, title: "删除这段对话？" },
      attachTo: document.body,
    })

    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))

    expect(wrapper.emitted("cancel")).toBeUndefined()
    wrapper.unmount()
  })

  // 验证模态框打开时 Tab / Shift+Tab 在「取消」「确认」之间循环，不逃逸到背景
  it("Tab 与 Shift+Tab 焦点在对话框内循环", async () => {
    const wrapper = mount(ConfirmDialog, {
      props: { visible: true, title: "删除这段对话？" },
      attachTo: document.body,
    })
    const cancel = wrapper.find('[data-testid="confirm-dialog-cancel-btn"]').element as HTMLElement
    const confirm = wrapper.find('[data-testid="confirm-dialog-confirm-btn"]').element as HTMLElement

    confirm.focus()
    confirm.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(cancel)

    cancel.focus()
    cancel.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(confirm)
    wrapper.unmount()
  })

  // 验证多个对话框实例的标题 ID 唯一，aria-labelledby 不会指错
  it("两个实例的 aria-labelledby 互不相同", () => {
    const a = mount(ConfirmDialog, { props: { visible: true, title: "甲" } })
    const b = mount(ConfirmDialog, { props: { visible: true, title: "乙" } })

    expect(a.find('[role="dialog"]').attributes("aria-labelledby")).not.toBe(
      b.find('[role="dialog"]').attributes("aria-labelledby"),
    )
  })
})
