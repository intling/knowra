<script setup lang="ts">
import { useChatStore } from "../../stores/chat"
import ConversationItem from "./ConversationItem.vue"

const emit = defineEmits<{ (e: "select"): void }>()

const chatStore = useChatStore()
</script>

<template>
  <div data-testid="conversation-list" class="flex flex-col px-3">
    <h2 class="px-1 pb-1.5 text-[11px] font-semibold tracking-[0.1em] text-ink-faint">最近对话</h2>

    <p
      v-if="chatStore.conversations.length === 0"
      data-testid="conversation-list-empty"
      class="px-1 py-2 text-xs leading-relaxed text-ink-faint"
    >
      暂无对话。点击「新对话」开始提问。
    </p>

    <ul v-else class="flex flex-col gap-0.5">
      <li v-for="conv in chatStore.conversations" :key="conv.id">
        <ConversationItem :conversation="conv" @select="emit('select')" />
      </li>
    </ul>
  </div>
</template>
