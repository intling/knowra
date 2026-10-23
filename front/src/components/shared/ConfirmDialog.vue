<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from "vue"

import { trapTab, uniqueId } from "../../shared/a11y/focus"

const props = defineProps<{
  visible: boolean
  title: string
  message?: string
  confirmText?: string
  cancelText?: string
  danger?: boolean
  confirmationText?: string
  confirmationLabel?: string
}>()

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()

const titleId = uniqueId("confirm-title")
const dialogRef = ref<HTMLElement | null>(null)
const cancelRef = ref<HTMLButtonElement | null>(null)
const confirmation = ref("")

function handleOverlayClick(event: MouseEvent) {
  if (
    (event.target as HTMLElement).dataset.testid === "confirm-dialog-overlay"
  ) {
    emit("cancel")
  }
}

/** 捕获阶段处理：确认框是最上层，Esc/Tab 不再交给抽屉等外层处理器。 */
function handleKeydown(event: KeyboardEvent) {
  if (!props.visible) return
  if (event.key === "Escape") {
    event.preventDefault()
    event.stopImmediatePropagation()
    emit("cancel")
    return
  }
  if (event.key === "Tab") {
    // 只在边界处循环（trapTab 内部 preventDefault），中间位置交给浏览器原生 Tab
    event.stopImmediatePropagation()
    trapTab(event, dialogRef.value)
  }
}

watch(
  () => props.visible,
  async (visible) => {
    if (!visible) return
    confirmation.value = ""
    await nextTick()
    cancelRef.value?.focus()
  },
  { immediate: true },
)

onMounted(() => document.addEventListener("keydown", handleKeydown, true))
onUnmounted(() => document.removeEventListener("keydown", handleKeydown, true))
</script>

<template>
  <div
    v-if="visible"
    data-testid="confirm-dialog-overlay"
    class="fixed inset-0 z-50 flex items-center justify-center bg-ink/35 p-4"
    @click="handleOverlayClick"
  >
    <div
      ref="dialogRef"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="titleId"
      class="w-full max-w-sm rounded-[var(--radius-card)] border border-line bg-surface shadow-[var(--shadow-popover)]"
      @click.stop
    >
      <div class="px-5 pt-5">
        <h3 :id="titleId" class="font-display text-lg font-semibold text-ink">
          {{ title }}
        </h3>
      </div>

      <div class="px-5 pt-2 pb-5">
        <slot>
          <p
            v-if="message"
            class="text-sm leading-6 text-ink-muted [overflow-wrap:anywhere]"
          >
            {{ message }}
          </p>
        </slot>
        <label v-if="confirmationText !== undefined" class="account-label mt-4">
          {{ confirmationLabel ?? "输入目标邮箱以确认" }}
          <input
            v-model="confirmation"
            data-testid="confirm-dialog-input"
            class="account-input mt-2"
            autocomplete="off"
            :placeholder="confirmationText"
          />
        </label>
      </div>

      <div class="flex justify-end gap-2 border-t border-line px-5 py-3.5">
        <button
          ref="cancelRef"
          type="button"
          data-testid="confirm-dialog-cancel-btn"
          class="rounded-[var(--radius-button)] border border-line bg-surface px-4 py-2 text-sm font-medium text-ink transition-colors hover:bg-paper-deep"
          @click="emit('cancel')"
        >
          {{ cancelText ?? "取消" }}
        </button>
        <button
          type="button"
          data-testid="confirm-dialog-confirm-btn"
          class="rounded-[var(--radius-button)] px-4 py-2 text-sm font-medium text-white transition-colors"
          :class="
            danger
              ? 'bg-cite hover:opacity-90'
              : 'bg-brand-700 hover:bg-brand-800 active:bg-brand-900'
          "
          :disabled="
            confirmationText !== undefined && confirmation !== confirmationText
          "
          @click="
            (confirmationText === undefined ||
              confirmation === confirmationText) &&
            emit('confirm')
          "
        >
          {{ confirmText ?? "确认" }}
        </button>
      </div>
    </div>
  </div>
</template>
