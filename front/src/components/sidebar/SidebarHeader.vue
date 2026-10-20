<script setup lang="ts">
import { useChatStore } from "../../stores/chat"

const emit = defineEmits<{ (e: "navigate"): void }>()

const chatStore = useChatStore()

function handleNewConversation() {
  chatStore.addConversation()
  emit("navigate")
}
</script>

<template>
  <div data-testid="sidebar-header" class="space-y-4 px-4 pt-5 pb-4">
    <div class="flex items-center gap-2.5 px-0.5">
      <span
        class="flex size-8 items-center justify-center rounded-lg bg-brand-700 font-display text-base font-semibold text-white"
        aria-hidden="true"
        >知</span
      >
      <div class="leading-tight">
        <h1 class="font-display text-xl font-semibold text-ink">知寻</h1>
        <p class="text-[11px] tracking-[0.14em] text-ink-faint">KNOWRA</p>
      </div>
    </div>

    <button
      data-testid="new-conversation-btn"
      type="button"
      class="flex w-full items-center justify-center gap-2 rounded-[var(--radius-button)] bg-brand-700 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-brand-800 active:bg-brand-900"
      @click="handleNewConversation"
    >
      <svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M12 5v14M5 12h14" />
      </svg>
      新对话
    </button>
  </div>
</template>
