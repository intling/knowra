<script setup lang="ts">
import { useChatStore } from "../../stores/chat"
import ConversationItem from "./ConversationItem.vue"

const chatStore = useChatStore()
</script>

<template>
  <div data-testid="conversation-list" class="flex flex-col gap-0.5 px-2 py-1">
    <!-- ── 空状态（无任何对话时）── -->
    <div
      v-if="chatStore.conversations.length === 0"
      data-testid="conversation-list-empty"
      class="flex flex-col items-center justify-center px-4 py-12 text-center"
    >
      <div
        class="flex size-10 items-center justify-center rounded-lg bg-neutral-100 text-neutral-400"
        aria-hidden="true"
      >
        <svg
          class="size-5"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path
            d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"
          />
          <path d="M8 10h.01M12 10h.01M16 10h.01" />
        </svg>
      </div>
      <p class="mt-2 text-xs text-neutral-500">暂无对话</p>
    </div>

    <div class="mt-6 mb-2 px-3 text-xs font-semibold text-neutral-500 uppercase tracking-wider">
      最近对话
    </div>
    <!-- ── 对话列表（时间倒序，不区分当前/历史）── -->
    <ConversationItem
      v-for="conv in chatStore.conversations"
      :key="conv.id"
      :conversation="conv"
    />
  </div>
</template>
