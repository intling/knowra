<script setup lang="ts">
import { computed, nextTick, ref } from "vue"

import { useChatStore, type Conversation } from "../../stores/chat"
import ConfirmDialog from "../shared/ConfirmDialog.vue"

const props = defineProps<{
  conversation: Conversation
}>()

const emit = defineEmits<{ (e: "select"): void }>()

const chatStore = useChatStore()

const isActive = computed(() => chatStore.activeConversationId === props.conversation.id)

const isTitlePending = computed(
  () =>
    !props.conversation.title ||
    props.conversation.title.trim().length === 0 ||
    props.conversation.title === "新对话",
)

const displayTitle = computed(() => (isTitlePending.value ? "新对话…" : props.conversation.title))

function select() {
  chatStore.setActiveConversation(props.conversation.id)
  emit("select")
}

// ── 重命名 ──
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
  }
  isRenaming.value = false
}

function handleRenameKeydown(event: KeyboardEvent) {
  if (event.key === "Enter") confirmRename()
  else if (event.key === "Escape") isRenaming.value = false
}

// ── 删除（二次确认，关闭后焦点回到删除按钮）──
const confirmingDelete = ref(false)
const deleteButtonRef = ref<HTMLButtonElement | null>(null)

function closeConfirm() {
  confirmingDelete.value = false
  nextTick(() => deleteButtonRef.value?.focus())
}

function confirmDelete() {
  confirmingDelete.value = false
  chatStore.deleteConversation(props.conversation.id)
}
</script>

<template>
  <div
    data-testid="conversation-item"
    class="group relative rounded-[var(--radius-button)] text-sm transition-colors"
    :class="isActive ? 'bg-neutral-100 shadow-[inset_2px_0_0_var(--color-brand-600)]' : 'hover:bg-paper/80'"
    @click="!isRenaming && select()"
  >
    <template v-if="!isRenaming">
      <button
        type="button"
        data-testid="conversation-select"
        class="block w-full truncate rounded-[var(--radius-button)] py-2 pr-16 pl-3 text-left"
        :class="isTitlePending ? 'text-ink-faint italic' : isActive ? 'font-medium text-ink' : 'text-ink-muted'"
        :aria-current="isActive ? 'page' : undefined"
        :title="displayTitle"
      >
        {{ displayTitle }}
      </button>

      <div
        data-testid="conversation-actions"
        class="absolute top-1/2 right-1 flex -translate-y-1/2 items-center gap-0.5 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100"
        :class="isActive ? 'opacity-100' : 'opacity-0'"
      >
        <button
          data-testid="rename-conversation-btn"
          type="button"
          class="rounded p-1.5 text-ink-faint transition-colors hover:bg-neutral-200 hover:text-ink"
          aria-label="重命名对话"
          title="重命名"
          @click.stop="startRename"
        >
          <svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
          </svg>
        </button>
        <button
          ref="deleteButtonRef"
          data-testid="delete-conversation-btn"
          type="button"
          class="rounded p-1.5 text-ink-faint transition-colors hover:bg-red-100 hover:text-red-700"
          aria-label="删除对话"
          title="删除"
          @click.stop="confirmingDelete = true"
        >
          <svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M3 6h18M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
          </svg>
        </button>
      </div>
    </template>

    <input
      v-else
      ref="renameInputRef"
      v-model="renameValue"
      type="text"
      aria-label="对话标题"
      class="w-full rounded-[var(--radius-button)] border border-brand-400 bg-surface px-2.5 py-1.5 text-sm text-ink outline-none ring-1 ring-brand-400"
      data-testid="rename-conversation-input"
      @click.stop
      @keydown="handleRenameKeydown"
      @blur="confirmRename"
    />

    <Teleport to="body">
      <ConfirmDialog
        :visible="confirmingDelete"
        title="删除这段对话？"
        :message="`「${displayTitle}」及其全部问答记录将被删除，且无法恢复。`"
        confirm-text="删除"
        danger
        @confirm="confirmDelete"
        @cancel="closeConfirm"
      />
    </Teleport>
  </div>
</template>
