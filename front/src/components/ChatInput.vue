<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue"

const props = withDefaults(
  defineProps<{
    modelValue?: string
    topK?: number
    loading?: boolean
    loadingStage?: "searching" | "generating" | null
  }>(),
  {
    modelValue: "",
    topK: 5,
    loading: false,
    loadingStage: null,
  },
)

const emit = defineEmits<{
  (e: "update:modelValue", value: string): void
  (e: "update:topK", value: number): void
  (e: "send"): void
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
const cannotSend = computed(() => trimmedQuery.value.length === 0 || props.loading)

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

// Auto-resize textarea
watch(localQuery, () => {
  if (!textareaRef.value) return
  textareaRef.value.style.height = "auto"
  textareaRef.value.style.height = `${textareaRef.value.scrollHeight}px`
})

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
    class="fixed bottom-0 left-0 right-0 z-20 border-t border-zinc-200/70 bg-zinc-50/90 px-3 py-3 backdrop-blur sm:px-4 sm:py-5"
  >
    <div
      class="mx-auto flex w-full max-w-3xl flex-col gap-3 rounded-2xl bg-white p-3 shadow-[0_10px_35px_rgba(15,23,42,0.12)] ring-1 ring-zinc-200 sm:p-4"
    >
      <!-- Top-K slider row -->
      <div class="flex items-center gap-3 px-1">
        <label
          for="topk-slider"
          class="shrink-0 text-xs font-medium text-zinc-500"
        >
          Top-K: <span class="text-zinc-900">{{ localTopK }}</span>
        </label>
        <input
          id="topk-slider"
          v-model.number="localTopK"
          type="range"
          min="1"
          max="50"
          step="1"
          class="h-1.5 w-24 cursor-pointer appearance-none rounded-full bg-zinc-200 accent-zinc-950 [&::-webkit-slider-thumb]:size-4 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-zinc-950"
          :disabled="loading"
        />
        <span class="text-xs text-zinc-400">1–50</span>
      </div>

      <!-- Input area -->
      <div class="flex items-end gap-2 sm:gap-3">
        <textarea
          ref="textareaRef"
          v-model="localQuery"
          data-testid="chat-input"
          class="max-h-48 min-h-12 flex-1 resize-none rounded-xl border-0 bg-transparent px-3 py-3 text-base leading-6 text-zinc-950 outline-none placeholder:text-zinc-400 focus:ring-0 sm:min-h-14"
          placeholder="向知寻提问"
          rows="1"
          :disabled="loading"
          @keydown="handleKeydown"
        />
        <button
          data-testid="send-button"
          class="flex h-12 shrink-0 items-center justify-center rounded-xl px-5 text-sm font-semibold transition sm:h-14"
          :class="
            cannotSend
              ? 'cursor-not-allowed bg-zinc-200 text-zinc-400'
              : 'bg-zinc-950 text-white shadow-sm hover:bg-zinc-800'
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
  </div>
</template>
