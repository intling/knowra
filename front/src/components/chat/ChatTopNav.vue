<script setup lang="ts">
/**
 * ChatTopNav — 对话区顶栏：移动端菜单按钮（由 ChatLayout 注入）、可重命名的对话标题、模型徽章。
 * 菜单按钮位于布局流内，不会与标题重叠。
 */
import { computed, inject, nextTick, ref, type ComponentPublicInstance } from "vue"

import { useChatStore } from "../../stores/chat"
import { mobileNavKey } from "../layout/mobileNav"

withDefaults(
  defineProps<{
    /** 当前对话模型名称，如 "deepseek-chat"、"gpt-4o" 等 */
    modelName?: string | null
  }>(),
  {
    modelName: null,
  },
)
const chatStore = useChatStore()
const mobileNav = inject(mobileNavKey, null)

function setTrigger(el: Element | ComponentPublicInstance | null) {
  if (mobileNav) mobileNav.triggerRef.value = el as HTMLButtonElement | null
}

/** 当前对话标题：空标题显示占位文案。 */
const conversationTitle = computed(() => {
  const conv = chatStore.activeConversation
  if (!conv || !conv.title || conv.title.trim().length === 0) return "新对话"
  return conv.title
})

// ── 点击标题重命名 ──
const isEditing = ref(false)
const editValue = ref("")
const editInputRef = ref<HTMLInputElement | null>(null)

function startEdit() {
  const conv = chatStore.activeConversation
  if (!conv) return
  editValue.value = conv.title
  isEditing.value = true
  nextTick(() => {
    editInputRef.value?.focus()
    editInputRef.value?.select()
  })
}

function confirmEdit() {
  const conv = chatStore.activeConversation
  const trimmed = editValue.value.trim()
  if (conv && trimmed && trimmed !== conv.title) {
    chatStore.renameConversation(conv.id, trimmed)
  }
  isEditing.value = false
}

function cancelEdit() {
  isEditing.value = false
}

function handleEditKeydown(event: KeyboardEvent) {
  if (event.key === "Enter") confirmEdit()
  else if (event.key === "Escape") cancelEdit()
}
</script>

<template>
  <header
    data-testid="chat-top-nav"
    class="sticky top-0 z-10 flex h-13 shrink-0 items-center border-b border-line bg-paper/90 backdrop-blur-sm"
  >
    <div class="flex w-full min-w-0 items-center gap-2 px-3 sm:px-5">
      <button
        v-if="mobileNav"
        v-show="mobileNav.isMobile.value"
        :ref="setTrigger"
        data-testid="hamburger-menu"
        type="button"
        class="flex size-9 shrink-0 items-center justify-center rounded-[var(--radius-button)] text-ink-muted transition-colors hover:bg-paper-deep hover:text-ink"
        aria-label="打开导航"
        aria-controls="mobile-sidebar"
        :aria-expanded="mobileNav.isOpen.value"
        @click="mobileNav.open()"
      >
        <svg data-testid="hamburger-icon" class="size-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" aria-hidden="true">
          <path d="M4 7h16M4 12h16M4 17h10" />
        </svg>
      </button>

      <div class="flex min-w-0 flex-1 items-center">
        <button
          v-if="!isEditing"
          data-testid="top-nav-title"
          class="group flex min-w-0 items-center gap-1.5 rounded-md px-1.5 py-1 transition-colors hover:bg-paper-deep"
          type="button"
          :aria-label="`对话标题：${conversationTitle}，点击重命名`"
          @click="startEdit"
        >
          <span class="truncate text-sm font-semibold text-ink">{{ conversationTitle }}</span>
          <svg class="size-3.5 shrink-0 text-ink-faint opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
          </svg>
        </button>
        <input
          v-else
          ref="editInputRef"
          v-model="editValue"
          data-testid="top-nav-title-input"
          type="text"
          aria-label="对话标题"
          class="min-w-0 flex-1 rounded-md border border-brand-400 bg-surface px-2 py-1 text-sm text-ink outline-none ring-1 ring-brand-400"
          @keydown="handleEditKeydown"
          @blur="confirmEdit"
        />
      </div>

      <span
        v-if="modelName"
        data-testid="top-nav-model"
        class="inline-flex max-w-[40%] shrink-0 items-center gap-1.5 truncate rounded-full border border-line bg-surface px-2.5 py-1 text-xs text-ink-muted"
        :title="`回答模型：${modelName}`"
      >
        <span class="size-1.5 shrink-0 rounded-full bg-brand-500" aria-hidden="true" />
        <span class="truncate">{{ modelName }}</span>
      </span>
    </div>
  </header>
</template>
