<script setup lang="ts">
import { nextTick, onUnmounted, ref, watch } from "vue"
import { trapTab, uniqueId } from "../../shared/a11y/focus"
const props = defineProps<{
  open: boolean
  title: string
  trigger?: HTMLElement | null
}>()
const emit = defineEmits<{ close: [] }>()
const id = uniqueId("admin-drawer"),
  panel = ref<HTMLElement | null>(null),
  closeButton = ref<HTMLButtonElement | null>(null)
let previous: HTMLElement | null = null,
  previousOverflow = ""
function keydown(event: KeyboardEvent) {
  if (!props.open) return
  if (event.key === "Escape") {
    event.preventDefault()
    event.stopImmediatePropagation()
    emit("close")
  } else trapTab(event, panel.value)
}
function restore() {
  document.body.style.overflow = previousOverflow
  document.removeEventListener("keydown", keydown)
  if (previous?.isConnected) previous.focus()
}
watch(
  () => props.open,
  async (open, wasOpen) => {
    if (open) {
      previous = props.trigger ?? (document.activeElement as HTMLElement)
      previousOverflow = document.body.style.overflow
      document.body.style.overflow = "hidden"
      document.addEventListener("keydown", keydown)
      await nextTick()
      closeButton.value?.focus()
    } else if (wasOpen) {
      await nextTick()
      restore()
    }
  },
  { immediate: true },
)
onUnmounted(() => {
  if (props.open) restore()
})
</script>
<template>
  <div
    v-if="open"
    class="fixed inset-0 z-40 flex justify-end bg-ink/35"
    @click.self="emit('close')"
  >
    <section
      ref="panel"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="id"
      class="flex h-dvh w-full min-w-0 flex-col overflow-y-auto border-l border-line bg-surface shadow-xl sm:max-w-xl"
    >
      <header
        class="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-line bg-surface px-5 py-4"
      >
        <h2 :id="id" class="font-display text-xl font-semibold">{{ title }}</h2>
        <button
          ref="closeButton"
          class="account-secondary shrink-0"
          aria-label="关闭抽屉"
          @click="emit('close')"
        >
          关闭 ×
        </button>
      </header>
      <div class="min-w-0 p-5 sm:p-7"><slot /></div>
    </section>
  </div>
</template>
