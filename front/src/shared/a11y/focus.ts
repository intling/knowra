/** 可聚焦元素选择器（排除 disabled 与 tabindex=-1）。 */
const FOCUSABLE =
  'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

export function focusableWithin(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE))
}

/**
 * 在 root 内循环 Tab 焦点：最后一个元素按 Tab 回到第一个，第一个按 Shift+Tab 到最后一个。
 * 返回 true 表示已处理该事件。
 */
export function trapTab(event: KeyboardEvent, root: HTMLElement | null): boolean {
  if (event.key !== "Tab" || !root) return false
  const items = focusableWithin(root)
  if (items.length === 0) return false
  const first = items[0]!
  const last = items[items.length - 1]!
  const active = document.activeElement
  if (event.shiftKey && (active === first || !root.contains(active))) {
    event.preventDefault()
    last.focus()
    return true
  }
  if (!event.shiftKey && (active === last || !root.contains(active))) {
    event.preventDefault()
    first.focus()
    return true
  }
  return false
}

let idSeq = 0

/** 页面级唯一 ID（跨应用实例也不重复），用于 aria-controls / aria-labelledby。 */
export function uniqueId(prefix: string): string {
  idSeq += 1
  return `${prefix}-${idSeq}`
}
