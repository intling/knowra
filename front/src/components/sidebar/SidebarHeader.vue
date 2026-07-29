<script setup lang="ts">
import { useChatStore } from "../../stores/chat"

const chatStore = useChatStore()

function handleNewConversation() {
  chatStore.addConversation()
}
</script>

<template>
  <div data-testid="sidebar-header" class="space-y-4 px-4 pb-3 pt-6">
    <!-- Logo + app name — 衬线体 wordmark -->
    <div class="flex items-center gap-2.5">
      <div
        class="flex size-8 items-center justify-center rounded-lg bg-brand-700 text-white"
        aria-hidden="true"
      >
        <svg
          class="size-5"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M12 2L2 7l10 5 10-5-10-5z" />
          <path d="M2 17l10 5 10-5" />
          <path d="M2 12l10 5 10-5" />
        </svg>
      </div>
      <div>
        <h1 class="font-display text-lg font-semibold leading-tight text-neutral-900">
          knowra
        </h1>
        <p class="text-xs text-neutral-500">个人知识助手</p>
      </div>
    </div>

    <!-- New conversation button -->
    <button
      data-testid="new-conversation-btn"
      class="flex w-full items-center justify-center gap-2 rounded-md bg-brand-700 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-brand-800 active:bg-brand-900"
      @click="handleNewConversation"
    >
      <svg
        class="size-4"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="M12 5v14M5 12h14" />
      </svg>
      新建对话
    </button>
  </div>
</template>
