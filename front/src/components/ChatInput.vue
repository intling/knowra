<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue"

// ── Types ────────────────────────────────────────────────────────────────────

export interface AttachedFile {
  id: string
  name: string
  size: number
  status: "pending" | "uploading" | "uploaded" | "error"
  error?: string
}

// ── Props ────────────────────────────────────────────────────────────────────

const props = withDefaults(
  defineProps<{
    modelValue?: string
    topK?: number
    loading?: boolean
    loadingStage?: "searching" | "generating" | null
    files?: AttachedFile[]
    forceReplace?: boolean
  }>(),
  {
    modelValue: "",
    topK: 5,
    loading: false,
    loadingStage: null,
    files: () => [],
    forceReplace: false,
  },
)

const emit = defineEmits<{
  (e: "update:modelValue", value: string): void
  (e: "update:topK", value: number): void
  (e: "update:forceReplace", value: boolean): void
  (e: "send"): void
  (e: "add-files"): void
  (e: "remove-file", id: string): void
}>()

const textareaRef = ref<HTMLTextAreaElement | null>(null)

const localQuery = computed({
  get: () => props.modelValue,
  set: (val: string) => emit("update:modelValue", val),
})

const localTopK = computed({
  get: () => props.topK,
  set: (val: number) => emit("update:topK", val),
})

const trimmedQuery = computed(() => localQuery.value.trim())

const hasUploadedFile = computed(() =>
  props.files.some((f) => f.status === "uploaded"),
)

const cannotSend = computed(
  () =>
    (trimmedQuery.value.length === 0 && !hasUploadedFile.value) ||
    props.loading,
)

const loadingLabel = computed(() => {
  if (!props.loading) return null
  if (props.loadingStage === "searching") return "搜索中..."
  if (props.loadingStage === "generating") return "生成回答中..."
  return "处理中..."
})

const buttonLabel = computed(() => loadingLabel.value ?? "发送")

// ── File helpers ─────────────────────────────────────────────────────────────

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

function handleAttachClick() {
  emit("add-files")
}

function handleRemoveFile(id: string) {
  emit("remove-file", id)
}

// ── Auto-resize textarea ─────────────────────────────────────────────────────

watch(localQuery, () => {
  if (!textareaRef.value) return
  textareaRef.value.style.height = "auto"
  textareaRef.value.style.height = `${textareaRef.value.scrollHeight}px`
})

// ── Keyboard handling ────────────────────────────────────────────────────────

function handleKeydown(event: KeyboardEvent) {
  // 输入法组字中的 Enter 用于确认候选词，不能发送或换行
  if (event.isComposing || event.keyCode === 229) return
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    // Ctrl+Enter or Cmd+Enter to insert newline
    event.preventDefault()
    const textarea = event.target as HTMLTextAreaElement
    const start = textarea.selectionStart
    const end = textarea.selectionEnd
    const value = textarea.value
    localQuery.value = value.slice(0, start) + "\n" + value.slice(end)
    void nextTick(() => {
      textarea.selectionStart = textarea.selectionEnd = start + 1
    })
  } else if (event.key === "Enter" && !event.shiftKey) {
    // Enter alone to send
    event.preventDefault()
    if (!cannotSend.value) {
      emit("send")
    }
  }
}

function handleSend() {
  if (!cannotSend.value) {
    emit("send")
  }
}

// ── Settings popover (Top-K 与上传策略) ─────────────────────────────────────

const settingsOpen = ref(false)
const settingsRef = ref<HTMLElement | null>(null)
const settingsButtonRef = ref<HTMLButtonElement | null>(null)

/** Esc 关闭设置弹层，并把焦点还给设置按钮。 */
function handleSettingsKeydown(event: KeyboardEvent) {
  if (event.key !== "Escape" || !settingsOpen.value) return
  event.preventDefault()
  event.stopPropagation()
  settingsOpen.value = false
  settingsButtonRef.value?.focus()
}

/** 供父组件（推荐问题）聚焦输入框。 */
function focus() {
  textareaRef.value?.focus()
}

defineExpose({ focus })

/** 点击弹层外部时关闭设置弹层。 */
function handleClickOutside(event: MouseEvent) {
  if (settingsRef.value && !settingsRef.value.contains(event.target as Node)) {
    settingsOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener("click", handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener("click", handleClickOutside)
})
</script>

<template>
  <div
    class="flex w-full flex-col rounded-[var(--radius-input)] border border-line bg-surface shadow-[var(--shadow-composer)] transition-colors focus-within:border-brand-300"
  >
    <!-- 附件 chips -->
    <div v-if="files.length > 0" data-testid="file-chips-area" class="flex flex-wrap gap-1.5 px-3 pt-3">
      <div
        v-for="file in files"
        :key="file.id"
        data-testid="file-chip"
        class="inline-flex max-w-full items-center gap-1.5 rounded-md border px-2 py-1 text-xs"
        :class="{
          'border-line bg-paper text-ink-muted': file.status === 'pending',
          'border-brand-200 bg-brand-50 text-brand-800': file.status === 'uploading',
          'border-emerald-200 bg-emerald-50 text-emerald-800': file.status === 'uploaded',
          'border-red-200 bg-red-50 text-red-800': file.status === 'error',
        }"
      >
        <svg class="size-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
        </svg>
        <span class="min-w-0 max-w-40 truncate">{{ file.name }}</span>
        <span class="shrink-0 opacity-60 tabular-nums">{{ formatFileSize(file.size) }}</span>
        <svg v-if="file.status === 'uploading'" data-testid="file-chip-spinner" class="size-3.5 shrink-0 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        <svg v-if="file.status === 'uploaded'" data-testid="file-chip-success" class="size-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <polyline points="20 6 9 17 4 12" />
        </svg>
        <svg v-if="file.status === 'error'" data-testid="file-chip-error" class="size-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="10" />
          <line x1="15" y1="9" x2="9" y2="15" />
          <line x1="9" y1="9" x2="15" y2="15" />
        </svg>
        <span v-if="file.status === 'error' && file.error" class="min-w-0 max-w-40 truncate text-red-700" :title="file.error">
          {{ file.error }}
        </span>
        <span class="sr-only">{{
          { pending: "等待上传", uploading: "上传中", uploaded: "已上传", error: "上传失败" }[file.status]
        }}</span>
        <button
          data-testid="file-chip-remove-btn"
          class="-mr-0.5 shrink-0 rounded p-0.5 opacity-60 transition hover:opacity-100"
          type="button"
          :aria-label="`移除文件 ${file.name}`"
          @click="handleRemoveFile(file.id)"
        >
          <svg class="size-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>
    </div>

    <!-- 文本框独占一行 -->
    <label for="chat-input-textarea" class="sr-only">向知寻提问</label>
    <textarea
      id="chat-input-textarea"
      ref="textareaRef"
      v-model="localQuery"
      data-testid="chat-input"
      class="max-h-48 min-h-[3.25rem] w-full resize-none border-0 bg-transparent px-4 pt-3.5 pb-1 text-[15px] leading-relaxed text-ink outline-none placeholder:text-ink-faint focus:ring-0 focus-visible:outline-none"
      placeholder="向知寻提问，Enter 发送"
      rows="1"
      :disabled="loading"
      @keydown="handleKeydown"
    />

    <!-- 工具栏 -->
    <div data-testid="chat-input-toolbar" class="flex items-center gap-1 px-2 pb-2">
      <button
        data-testid="attach-button"
        class="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-[var(--radius-button)] px-2.5 text-sm text-ink-muted transition-colors hover:bg-paper-deep hover:text-ink disabled:opacity-50"
        type="button"
        aria-label="添加附件"
        :disabled="loading"
        @click="handleAttachClick"
      >
        <svg class="size-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
        </svg>
        <span class="hidden sm:inline" aria-hidden="true">资料</span>
      </button>

      <div ref="settingsRef" class="relative shrink-0" @keydown="handleSettingsKeydown">
        <button
          ref="settingsButtonRef"
          data-testid="settings-button"
          class="inline-flex h-9 items-center gap-1.5 rounded-[var(--radius-button)] px-2.5 text-sm text-ink-muted transition-colors hover:bg-paper-deep hover:text-ink"
          type="button"
          :aria-label="`检索设置，当前每次检索 ${localTopK} 段`"
          aria-haspopup="dialog"
          :aria-expanded="settingsOpen"
          @click="settingsOpen = !settingsOpen"
        >
          <svg class="size-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3" />
            <path d="M1 14h6M9 8h6M17 16h6" />
          </svg>
          <span class="tabular-nums" aria-hidden="true">检索 {{ localTopK }} 段</span>
        </button>

        <div
          v-if="settingsOpen"
          data-testid="settings-popover"
          role="dialog"
          aria-label="检索设置"
          class="absolute bottom-full left-0 z-20 mb-2 w-64 max-w-[calc(100vw-2rem)] rounded-[var(--radius-card)] border border-line bg-surface p-4 shadow-[var(--shadow-popover)]"
        >
          <div class="flex items-center justify-between">
            <label for="topk-slider" class="text-xs font-medium text-ink-muted">检索片段数（Top-K）</label>
            <span class="text-sm font-semibold text-ink tabular-nums">{{ localTopK }}</span>
          </div>
          <div class="mt-2 flex items-center gap-2">
            <input
              id="topk-slider"
              v-model.number="localTopK"
              type="range"
              min="1"
              max="50"
              step="1"
              class="h-1.5 flex-1 cursor-pointer accent-brand-700"
              :disabled="loading"
            />
            <span class="text-[11px] text-ink-faint">1–50</span>
          </div>
          <label class="mt-3 flex cursor-pointer items-center gap-2 border-t border-line pt-3 text-xs text-ink-muted select-none">
            <input
              type="checkbox"
              :checked="props.forceReplace"
              class="size-3.5 accent-brand-700"
              @change="emit('update:forceReplace', ($event.target as HTMLInputElement).checked)"
            />
            上传时替换已存在的同名文件
          </label>
        </div>
      </div>

      <span class="ml-auto hidden pr-2 text-[11px] text-ink-faint min-[480px]:inline">Shift+Enter 换行</span>

      <button
        data-testid="send-button"
        class="ml-auto flex size-9 shrink-0 items-center justify-center rounded-full transition-colors min-[480px]:ml-0"
        :class="
          cannotSend && !loading
            ? 'bg-neutral-200 text-ink-faint'
            : 'bg-brand-700 text-white hover:bg-brand-800 active:bg-brand-900 disabled:opacity-80'
        "
        type="button"
        :disabled="cannotSend"
        aria-label="发送"
        @click="handleSend"
      >
        <svg v-if="loading" class="size-4 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        <svg v-else class="size-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M12 19V5M5 12l7-7 7 7" />
        </svg>
        <span class="sr-only">{{ buttonLabel }}</span>
      </button>
    </div>
  </div>
</template>
