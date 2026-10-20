import type { InjectionKey, Ref } from "vue"

/** ChatLayout 提供给顶栏的移动端导航能力（菜单按钮渲染在顶栏布局流内）。 */
export interface MobileNav {
  isMobile: Ref<boolean>
  isOpen: Ref<boolean>
  open: () => void
  triggerRef: Ref<HTMLButtonElement | null>
}

export const mobileNavKey: InjectionKey<MobileNav> = Symbol("mobileNav")
