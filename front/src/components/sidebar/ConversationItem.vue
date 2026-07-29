<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue"

import { useChatStore, type Conversation } from "../../stores/chat"

const props = defineProps<{
  conversation: Conversation
}>()

const chatStore = useChatStore()

// ── Active state ───────────────────────────────────────────────────────────

const isActive = ref(chatStore.activeConversationId === props.conversation.id)

watch(
  () => chatStore.activeConversationId,
  (newId) => {
    isActive.value = newId === props.conversation.id
  },
)

// ── Display title ──────────────────────────────────────────────────────────

/** 侧边栏展示标题：空标题时显示"新对话…"占位 */
const displayTitle = computed(() => {
  if (props.conversation.title && props.conversation.title.trim().length > 0) {
    return props.conversation.title
  }
  return "新对话…"
})

/** 标题是否仍处于待生成状态（空标题或仅占位） */
const isTitlePending = computed(() => {
  return (
    !props.conversation.title ||
    props.conversation.title.trim().length === 0 ||
    props.conversation.title === "新对话"
  )
})

// ── Rename ─────────────────────────────────────────────────────────────────

const isRenaming = ref(false)
const renameValue = ref("")
const renameInputRef = ref<HTMLInputElement | null>(null)

function startRename() {
  renameValue.value = props.conversation.title
  isRenaming.value = true
  nextTick(() => {
    renameInputRef.value?.focus()
    renameInputRef.value?.select()
  })
}

function confirmRename() {
  const trimmed = renameValue.value.trim()
  if (trimmed && trimmed !== props.conversation.title) {
    chatStore.renameConversation(props.conversation.id, trimmed)
  } else if (!trimmed && !props.conversation.title) {
    // 用户清空了标题 → 不操作，保持占位状态
  }
  isRenaming.value = false
}

function cancelRename() {
  isRenaming.value = false
}

function handleRenameKeydown(event: KeyboardEvent) {
  if (event.key === "Enter") {
    confirmRename()
  } else if (event.key === "Escape") {
    cancelRename()
  }
}

// ── Delete ─────────────────────────────────────────────────────────────────

function handleDelete() {
  chatStore.deleteConversation(props.conversation.id)
}
</script>

<template>
  <div
    :data-testid="'conversation-item'"
    class="group relative cursor-pointer rounded-md px-3 py-2.5 text-sm transition-colors hover:bg-neutral-100"
    :class="{ 'bg-neutral-100': isActive }"
    @click="chatStore.setActiveConversation(conversation.id)"
  >
    <!-- Normal display -->
    <template v-if="!isRenaming">
      <p
        class="truncate pr-14 text-sm"
        :class="isTitlePending ? 'text-neutral-400 italic' : 'text-neutral-700'"
      >
        <!-- 待生成标题时显示细微的脉冲动画指示 -->
        <span
          v-if="isTitlePending && isActive"
          class="mr-1.5 inline-block size-1.5 animate-pulse rounded-full bg-brand-400 align-middle"
          aria-hidden="true"
        />
        {{ displayTitle }}
      </p>

      <!-- Hover action buttons -->
      <div
        class="absolute right-1 top-1/2 flex -translate-y-1/2 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100"
      >
        <button
          data-testid="rename-conversation-btn"
          class="rounded p-1.5 text-neutral-400 transition-colors hover:bg-neutral-200 hover:text-neutral-600"
          title="重命名"
          @click.stop="startRename"
        >
          <svg
            class="size-3.5"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
          </svg>
        </button>
        <button
          data-testid="delete-conversation-btn"
          class="rounded p-1.5 text-neutral-400 transition-colors hover:bg-red-100 hover:text-red-600"
          title="删除"
          @click.stop="handleDelete"
        >
          <svg
            class="size-3.5"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M3 6h18M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
          </svg>
        </button>
      </div>
    </template>

    <!-- Rename input -->
    <template v-else>
      <input
        ref="renameInputRef"
        v-model="renameValue"
        type="text"
        class="w-full rounded-md border border-brand-400 bg-white px-2 py-1 text-sm text-neutral-900 outline-none ring-1 ring-brand-400"
        data-testid="rename-conversation-input"
        @keydown="handleRenameKeydown"
        @blur="confirmRename"
      />
    </template>
  </div>
</template>
