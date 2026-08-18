<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue"

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

const buttonLabel = computed(() => {
  if (loadingLabel.value) return loadingLabel.value
  return "发送"
})

// ── File helpers ─────────────────────────────────────────────────────────────

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
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
</script>

<template>
  <div
    class="flex w-full flex-col gap-3 rounded-2xl border border-[#e5e7eb] bg-white p-3 sm:p-4"
    style="box-shadow: 0 4px 20px rgba(0,0,0,0.05)"
  >
      <!-- File chips area -->
      <div
        v-if="files.length > 0"
        data-testid="file-chips-area"
        class="flex flex-wrap gap-2 px-1"
      >
        <div
          v-for="file in files"
          :key="file.id"
          data-testid="file-chip"
          class="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs transition"
          :class="{
            'border-neutral-200 bg-neutral-50 text-neutral-700': file.status === 'pending',
            'border-brand-200 bg-brand-50 text-brand-700': file.status === 'uploading',
            'border-emerald-200 bg-emerald-50 text-emerald-700': file.status === 'uploaded',
            'border-red-200 bg-red-50 text-red-700': file.status === 'error',
          }"
        >
          <!-- File icon -->
          <svg
            class="size-3.5 shrink-0"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
          </svg>

          <!-- File name -->
          <span class="max-w-40 truncate">{{ file.name }}</span>

          <!-- File size -->
          <span class="shrink-0 opacity-60">{{ formatFileSize(file.size) }}</span>

          <!-- Uploading spinner -->
          <svg
            v-if="file.status === 'uploading'"
            data-testid="file-chip-spinner"
            class="size-3.5 shrink-0 animate-spin"
            viewBox="0 0 24 24"
            fill="none"
            aria-hidden="true"
          >
            <circle
              class="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              stroke-width="4"
            />
            <path
              class="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
            />
          </svg>

          <!-- Uploaded checkmark -->
          <svg
            v-if="file.status === 'uploaded'"
            data-testid="file-chip-success"
            class="size-3.5 shrink-0"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2.5"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <polyline points="20 6 9 17 4 12" />
          </svg>

          <!-- Error indicator -->
          <svg
            v-if="file.status === 'error'"
            data-testid="file-chip-error"
            class="size-3.5 shrink-0"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <circle cx="12" cy="12" r="10" />
            <line x1="15" y1="9" x2="9" y2="15" />
            <line x1="9" y1="9" x2="15" y2="15" />
          </svg>

          <!-- Error message tooltip -->
          <span
            v-if="file.status === 'error' && file.error"
            class="max-w-32 truncate text-red-600"
          >
            {{ file.error }}
          </span>

          <!-- Remove button -->
          <button
            data-testid="file-chip-remove-btn"
            class="ml-0.5 shrink-0 rounded p-0.5 opacity-60 transition hover:opacity-100"
            type="button"
            aria-label="移除文件"
            @click="handleRemoveFile(file.id)"
          >
            <svg
              class="size-3"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      </div>

      <!-- Force replace checkbox: only visible when files are attached -->
      <div v-if="files.length > 0" class="flex items-center gap-2 px-1">
        <label class="flex cursor-pointer items-center gap-1.5 text-xs text-neutral-500 select-none">
          <input
            type="checkbox"
            :checked="props.forceReplace"
            class="size-3.5 rounded border-neutral-300 text-brand-700 focus:ring-brand-600"
            @change="emit('update:forceReplace', ($event.target as HTMLInputElement).checked)"
          />
          替换已存在的同名文件
        </label>
      </div>

      <!-- Top-K slider row -->
      <div class="flex items-center gap-3 px-1">
        <label
          for="topk-slider"
          class="shrink-0 text-xs font-medium text-neutral-500"
        >
          Top-K: <span class="tabular-nums text-neutral-800">{{ localTopK }}</span>
        </label>
        <input
          id="topk-slider"
          v-model.number="localTopK"
          type="range"
          min="1"
          max="50"
          step="1"
          class="h-1.5 w-24 cursor-pointer appearance-none rounded-full bg-neutral-200 accent-brand-700 [&::-webkit-slider-thumb]:size-4 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-brand-700 [&::-webkit-slider-thumb]:shadow-sm"
          :disabled="loading"
        />
        <span class="text-xs text-neutral-400">1–50</span>
      </div>

      <!-- Input area -->
      <div class="flex items-end gap-2 sm:gap-3">
        <textarea
          ref="textareaRef"
          v-model="localQuery"
          data-testid="chat-input"
          class="max-h-48 min-h-12 flex-1 resize-none rounded-lg border-0 bg-transparent px-3 py-3 text-[15px] leading-relaxed text-neutral-800 outline-none placeholder:text-neutral-400 focus:ring-0 sm:min-h-14"
          placeholder="向知寻提问"
          rows="1"
          :disabled="loading"
          @keydown="handleKeydown"
        />
        <!-- Attach button -->
        <button
          data-testid="attach-button"
          class="flex h-12 shrink-0 items-center justify-center rounded-lg px-3 text-neutral-400 transition hover:bg-neutral-100 hover:text-neutral-600 sm:h-14"
          type="button"
          aria-label="添加附件"
          :disabled="loading"
          @click="handleAttachClick"
        >
          <svg
            class="size-5"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
          </svg>
        </button>
        <button
          data-testid="send-button"
          class="flex h-12 shrink-0 items-center justify-center rounded-lg px-5 text-sm font-semibold transition sm:h-14"
          :class="
            cannotSend
              ? 'cursor-not-allowed bg-neutral-200 text-neutral-400'
              : 'bg-brand-700 text-white shadow-sm transition-colors hover:bg-brand-800 active:bg-brand-900'
          "
          type="button"
          :disabled="cannotSend"
          aria-label="发送"
          @click="handleSend"
        >
          <span v-if="loading" class="flex items-center gap-1.5">
            <svg
              class="size-4 animate-spin"
              viewBox="0 0 24 24"
              fill="none"
              aria-hidden="true"
            >
              <circle
                class="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                stroke-width="4"
              />
              <path
                class="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
              />
            </svg>
            {{ buttonLabel }}
          </span>
          <span v-else>{{ buttonLabel }}</span>
        </button>
      </div>
    </div>
  </template>
