<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from "vue"

import {
  getDocumentChunkJob,
  getLatestParsedDocumentChunkJob,
  getParsedDocumentChunks,
  rechunkParsedDocument,
} from "../api/documentChunking"
import type {
  DocumentChunk,
  DocumentChunkJob,
  DocumentChunkPage,
} from "../api/documentChunking"
import {
  createDocumentParseJob,
  getDocumentParseJob,
  getParsedDocumentForUpload,
} from "../api/documentParsing"
import type {
  DocumentParseConflictError,
  DocumentParseJob,
  ParsedDocument,
} from "../api/documentParsing"
import type { UploadedFile } from "../api/uploads"
import { createLogger, getRingBuffer } from "../shared/logger"
import { useAppStore } from "../stores/app"
import { useUserStore } from "../stores/user"

/** Lazy logger — getRingBuffer() is only available after main.ts initLogger(). */
let _logger: ReturnType<typeof createLogger> | null = null
function log() {
  if (!_logger) _logger = createLogger("views:Home", getRingBuffer())
  return _logger
}

const appStore = useAppStore()
const userStore = useUserStore()
const message = ref("")
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)
const isUploading = ref(false)
const uploadFeedback = ref<string | null>(null)
const uploadedFileInfo = ref<UploadedFile | null>(null)
const isParsing = ref(false)
const parseFeedback = ref<string | null>(null)
const canRetryParse = ref(false)
const parsedDocumentInfo = ref<ParsedDocument | null>(null)
const currentChunkJob = ref<DocumentChunkJob | null>(null)
const chunkPage = ref<DocumentChunkPage | null>(null)
const chunkFeedback = ref<string | null>(null)
const isLoadingChunks = ref(false)
const isRechunking = ref(false)
const chunkStatusMode = ref<"initial" | "rechunk">("initial")
const chunkPollGeneration = ref(0)
const rechunkMaxTokens = ref(512)
const rechunkMergePeers = ref(true)

const ACTIVE_PARSE_STATUSES = new Set<DocumentParseJob["status"]>([
  "queued",
  "running",
])
const PARSE_STATUS_POLL_INTERVAL_MS = 1000
const PARSE_STATUS_MAX_POLLS = 60
const ACTIVE_CHUNK_STATUSES = new Set<DocumentChunkJob["status"]>([
  "queued",
  "running",
])
const CHUNK_STATUS_POLL_INTERVAL_MS = 1000
const CHUNK_STATUS_MAX_POLLS = 60
const CHUNK_PREVIEW_LIMIT = 20

const canSend = computed(
  () =>
    !isUploading.value &&
    (message.value.trim().length > 0 ||
      (selectedFile.value !== null && userStore.currentUser !== null)),
)
const userLabel = computed(
  () => userStore.currentUser?.display_name ?? "当前用户未连接",
)
const uploadStatus = computed(() => {
  if (isUploading.value) {
    return "上传中..."
  }

  if (userStore.userError) {
    return "当前用户不可用，无法上传附件"
  }

  return uploadFeedback.value
})
const parseStatusText = computed(() => {
  if (isParsing.value) return "解析中"
  if (parseFeedback.value) return parseFeedback.value
  if (uploadedFileInfo.value) return "等待自动解析"
  return null
})
const chunkItems = computed(() =>
  [...(chunkPage.value?.items ?? [])].sort(
    (left, right) => left.sequence_index - right.sequence_index,
  ),
)
const hasChunkPreview = computed(() => chunkPage.value !== null)
const chunkPanelVisible = computed(
  () =>
    parsedDocumentInfo.value !== null ||
    currentChunkJob.value !== null ||
    hasChunkPreview.value ||
    chunkFeedback.value !== null ||
    isLoadingChunks.value,
)
const isChunkJobRunning = computed(
  () =>
    isRechunking.value ||
    (currentChunkJob.value !== null &&
      ACTIVE_CHUNK_STATUSES.has(currentChunkJob.value.status)),
)
const chunkStatusText = computed(() => {
  if (chunkFeedback.value) return chunkFeedback.value
  if (isLoadingChunks.value && currentChunkJob.value === null) return "分块状态加载中"

  const job = currentChunkJob.value
  if (job === null) {
    return hasChunkPreview.value ? "分块成功" : null
  }

  const isRechunk = chunkStatusMode.value === "rechunk"
  if (ACTIVE_CHUNK_STATUSES.has(job.status)) {
    return isRechunk ? "重新分块中" : "分块中"
  }

  if (job.status === "succeeded") return "分块成功"

  if (job.status === "failed") {
    const reason = job.error_message ? `：${job.error_message}` : ""
    return `${isRechunk ? "重新分块失败" : "分块失败"}${reason}`
  }

  if (job.status === "superseded") return "分块结果已被更新"

  return null
})
const rechunkConfig = computed(() => ({
  max_tokens: rechunkMaxTokens.value,
  merge_peers: rechunkMergePeers.value,
}))

const resizeInput = async () => {
  await nextTick()

  if (!textareaRef.value) {
    return
  }

  textareaRef.value.style.height = "auto"
  textareaRef.value.style.height = `${textareaRef.value.scrollHeight}px`
}

const handleInput = () => {
  void resizeInput()
}

const openFilePicker = () => {
  fileInputRef.value?.click()
}

const handleFileChange = (event: Event) => {
  const input = event.target as HTMLInputElement
  selectedFile.value = input.files?.[0] ?? null
  uploadFeedback.value = null
  if (selectedFile.value) {
    log().info("用户选择了文件", {
      fileName: selectedFile.value.name,
      fileSize: selectedFile.value.size,
      fileType: selectedFile.value.type,
    })
  }
}

const removeSelectedFile = () => {
  selectedFile.value = null
  uploadFeedback.value = null
  uploadedFileInfo.value = null
  parseFeedback.value = null
  canRetryParse.value = false
  resetChunkState()

  if (fileInputRef.value) {
    fileInputRef.value.value = ""
  }
}

const clearFileInput = () => {
  selectedFile.value = null

  if (fileInputRef.value) {
    fileInputRef.value.value = ""
  }
}

const resetChunkState = () => {
  chunkPollGeneration.value += 1
  parsedDocumentInfo.value = null
  currentChunkJob.value = null
  chunkPage.value = null
  chunkFeedback.value = null
  isLoadingChunks.value = false
  isRechunking.value = false
  chunkStatusMode.value = "initial"
}

const wait = (milliseconds: number) =>
  new Promise<void>((resolve) => {
    window.setTimeout(resolve, milliseconds)
  })

const waitForParseJobCompletion = async (
  initialJob: DocumentParseJob,
): Promise<DocumentParseJob> => {
  let job = initialJob

  for (
    let pollCount = 0;
    ACTIVE_PARSE_STATUSES.has(job.status) && pollCount < PARSE_STATUS_MAX_POLLS;
    pollCount += 1
  ) {
    job = await getDocumentParseJob(job.id)
    if (ACTIVE_PARSE_STATUSES.has(job.status)) {
      await wait(PARSE_STATUS_POLL_INTERVAL_MS)
    }
  }

  return job
}

const applyParseJobResult = (job: DocumentParseJob) => {
  if (job.status === "succeeded") {
    parseFeedback.value = "解析成功"
    return
  }

  if (job.status === "failed") {
    parseFeedback.value = job.error_message || "解析失败，请重试"
    canRetryParse.value = true
    return
  }

  if (job.status === "cancelled") {
    parseFeedback.value = "解析已取消"
    canRetryParse.value = true
    return
  }

  parseFeedback.value = "解析仍在处理中"
}

const getErrorText = (error: unknown, fallback: string) =>
  error instanceof Error ? error.message : fallback

const isChunkConflictError = (
  error: unknown,
): error is { status: 409; detail: string; job: DocumentChunkJob } =>
  typeof error === "object" &&
  error !== null &&
  "status" in error &&
  (error as { status?: unknown }).status === 409 &&
  "detail" in error &&
  typeof (error as { detail?: unknown }).detail === "string" &&
  "job" in error

const loadChunkJob = async (
  jobId: string,
  { allowMissing = false }: { allowMissing?: boolean } = {},
) => {
  try {
    currentChunkJob.value = await getDocumentChunkJob(jobId)
  } catch (error) {
    if (!allowMissing) {
      throw error
    }
  }
}

const loadLatestChunkJob = async (
  parsedDocumentId: string,
  { allowMissing = false }: { allowMissing?: boolean } = {},
) => {
  try {
    currentChunkJob.value =
      await getLatestParsedDocumentChunkJob(parsedDocumentId)
  } catch (error) {
    if (!allowMissing) {
      throw error
    }
  }
}

const loadChunkPreview = async (parsedDocument: ParsedDocument) => {
  const page = await getParsedDocumentChunks(parsedDocument.id, {
    offset: 0,
    limit: CHUNK_PREVIEW_LIMIT,
  })
  chunkPage.value = page
  return page
}

const pollChunkJobUntilSettled = async (
  initialJob: DocumentChunkJob,
  parsedDocument: ParsedDocument,
  pollGeneration: number,
) => {
  let job = initialJob

  for (
    let pollCount = 0;
    ACTIVE_CHUNK_STATUSES.has(job.status) &&
    pollCount < CHUNK_STATUS_MAX_POLLS;
    pollCount += 1
  ) {
    try {
      job = await getDocumentChunkJob(job.id)
    } catch (error) {
      if (pollGeneration === chunkPollGeneration.value) {
        chunkFeedback.value = getErrorText(error, "分块状态读取失败")
      }
      return
    }

    if (pollGeneration !== chunkPollGeneration.value) return

    currentChunkJob.value = job
    if (ACTIVE_CHUNK_STATUSES.has(job.status)) {
      await wait(CHUNK_STATUS_POLL_INTERVAL_MS)
    }
  }

  if (pollGeneration !== chunkPollGeneration.value) return

  if (job.status === "succeeded") {
    try {
      await loadChunkPreview(parsedDocument)
    } catch (error) {
      if (pollGeneration === chunkPollGeneration.value) {
        chunkFeedback.value = getErrorText(error, "分块状态读取失败")
      }
    }
  }
}

const startChunkJobPolling = (
  initialJob: DocumentChunkJob,
  parsedDocument: ParsedDocument,
) => {
  const pollGeneration = chunkPollGeneration.value
  void pollChunkJobUntilSettled(initialJob, parsedDocument, pollGeneration)
}

const loadInitialChunkState = async (parsedDocument: ParsedDocument) => {
  isLoadingChunks.value = true
  chunkFeedback.value = null
  chunkStatusMode.value = "initial"

  try {
    const page = await loadChunkPreview(parsedDocument)
    if (page.items.length > 0) {
      currentChunkJob.value = null
      return
    }

    await loadLatestChunkJob(parsedDocument.id, { allowMissing: true })
    if (
      currentChunkJob.value !== null &&
      ACTIVE_CHUNK_STATUSES.has(currentChunkJob.value.status)
    ) {
      startChunkJobPolling(currentChunkJob.value, parsedDocument)
    }
  } catch (error) {
    chunkFeedback.value = getErrorText(error, "分块状态读取失败")
  } finally {
    isLoadingChunks.value = false
  }
}

const loadParsedDocumentAndChunks = async (uploaded: UploadedFile) => {
  try {
    const parsedDocument = await getParsedDocumentForUpload(uploaded.id)
    parsedDocumentInfo.value = parsedDocument
    await loadInitialChunkState(parsedDocument)
  } catch (error) {
    chunkFeedback.value = getErrorText(error, "分块状态读取失败")
  }
}

const startParseForUpload = async (uploaded: UploadedFile) => {
  if (isParsing.value) return

  uploadedFileInfo.value = uploaded
  isParsing.value = true
  parseFeedback.value = null
  canRetryParse.value = false
  resetChunkState()

  try {
    const job = await createDocumentParseJob(uploaded.id)
    const completedJob = await waitForParseJobCompletion(job)
    applyParseJobResult(completedJob)
    if (completedJob.status === "succeeded") {
      await loadParsedDocumentAndChunks(uploaded)
    }
  } catch (error: unknown) {
    if (
      typeof error === "object" &&
      error !== null &&
      "status" in error &&
      (error as DocumentParseConflictError).status === 409
    ) {
      const conflict = error as DocumentParseConflictError
      parseFeedback.value = conflict.detail
    } else {
      parseFeedback.value =
        error instanceof Error ? error.message : "解析失败，请重试"
      canRetryParse.value = true
    }
  } finally {
    isParsing.value = false
  }
}

const handleParse = async () => {
  if (!uploadedFileInfo.value) return

  await startParseForUpload(uploadedFileInfo.value)
}

const handleSend = async () => {
  if (!canSend.value || isUploading.value) {
    return
  }

  let uploadedForParsing: UploadedFile | null = null

  if (selectedFile.value) {
    if (!userStore.currentUser) {
      uploadFeedback.value = "当前用户不可用，无法上传附件"
      return
    }

    isUploading.value = true
    uploadFeedback.value = null
    uploadedFileInfo.value = null
    parseFeedback.value = null
    canRetryParse.value = false
    resetChunkState()

    try {
      const uploaded = await uploadFile(selectedFile.value)
      uploadedFileInfo.value = uploaded
      uploadedForParsing = uploaded
      uploadFeedback.value = `${uploaded.original_filename} 上传成功`
      log().info("文件上传成功", {
        fileName: uploaded.original_filename,
        fileId: uploaded.id,
        byteSize: uploaded.byte_size,
      })
      clearFileInput()
    } catch (error) {
      uploadFeedback.value =
        error instanceof Error ? error.message : "上传失败，请重试"
      log().error("文件上传失败", error)
      return
    } finally {
      isUploading.value = false
    }
  }

  if (uploadedForParsing) {
    await startParseForUpload(uploadedForParsing)
  }

  message.value = ""
  void resizeInput()
}

const handleRechunk = async () => {
  if (!parsedDocumentInfo.value || isChunkJobRunning.value) return

  chunkPollGeneration.value += 1
  isRechunking.value = true
  chunkStatusMode.value = "rechunk"
  chunkFeedback.value = null

  try {
    const job = await rechunkParsedDocument(
      parsedDocumentInfo.value.id,
      rechunkConfig.value,
    )
    currentChunkJob.value = job
    await loadChunkJob(job.id)

    if (currentChunkJob.value?.status === "succeeded") {
      await loadChunkPreview(parsedDocumentInfo.value)
    } else if (
      currentChunkJob.value !== null &&
      ACTIVE_CHUNK_STATUSES.has(currentChunkJob.value.status)
    ) {
      startChunkJobPolling(currentChunkJob.value, parsedDocumentInfo.value)
    }
  } catch (error: unknown) {
    if (isChunkConflictError(error)) {
      currentChunkJob.value = error.job
      chunkFeedback.value = error.detail
    } else {
      chunkFeedback.value = getErrorText(error, "重新分块失败")
    }
  } finally {
    isRechunking.value = false
  }
}

const formatHeadingPath = (chunk: DocumentChunk) =>
  chunk.heading_path && chunk.heading_path.length > 0
    ? chunk.heading_path.join(" / ")
    : "未命名位置"

const formatPageNumbers = (chunk: DocumentChunk) => {
  if (!chunk.page_numbers || chunk.page_numbers.length === 0) return "页码未知"
  return chunk.page_numbers.map((page) => `第 ${page} 页`).join("、")
}

const handleInputKeydown = (event: KeyboardEvent) => {
  if (event.key !== "Enter" || event.shiftKey) {
    return
  }

  event.preventDefault()
  handleSend()
}

onMounted(() => {
  log().info("首页组件挂载")
  void appStore.refreshHealth()
  void userStore.loadCurrentUser()
  void resizeInput()
})
</script>

<template>
  <section
    class="flex min-h-[calc(100vh-7rem)] flex-col bg-zinc-50 pb-36 sm:pb-40"
  >
    <div class="mx-auto flex w-full max-w-3xl flex-1 flex-col px-4 py-8 sm:py-12">
      <div class="mb-10 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p class="text-sm font-medium text-zinc-500">
            个人知识库 AI 助手
          </p>
          <h1 class="mt-2 text-2xl font-semibold tracking-normal text-zinc-950 sm:text-3xl">
            knowra
          </h1>
        </div>
        <div
          class="rounded-full border border-zinc-200 bg-white px-3 py-1.5 text-sm text-zinc-600 shadow-sm"
        >
          {{ userLabel }}
        </div>
      </div>

      <div class="grid flex-1 place-items-center text-center">
        <div class="max-w-xl">
          <p class="text-xl font-semibold tracking-normal text-zinc-900 sm:text-2xl">
            今天想了解什么？
          </p>
          <p class="mt-3 text-sm leading-6 text-zinc-500 sm:text-base">
            输入问题后，knowra 会围绕你的私有资料组织回答，并为后续引用来源展示保留空间。
          </p>
        </div>
      </div>

      <section
        v-if="chunkPanelVisible"
        data-testid="chunk-panel"
        class="mt-8 border-t border-zinc-200 pt-5 text-left"
      >
        <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p
              v-if="chunkStatusText"
              data-testid="chunk-status"
              class="text-sm font-medium text-zinc-700"
            >
              {{ chunkStatusText }}
            </p>
            <p class="mt-1 text-sm text-zinc-500">
              当前阶段表示分块完成后可预览。
            </p>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <label class="flex items-center gap-2 text-sm text-zinc-600">
              <span>Tokens</span>
              <input
                v-model.number="rechunkMaxTokens"
                class="h-9 w-20 rounded-lg border border-zinc-200 bg-white px-2 text-sm text-zinc-900 outline-none focus:border-zinc-400"
                type="number"
                min="1"
                :disabled="isChunkJobRunning"
              />
            </label>
            <label class="flex h-9 items-center gap-2 rounded-lg border border-zinc-200 bg-white px-3 text-sm text-zinc-600">
              <input
                v-model="rechunkMergePeers"
                class="size-4 accent-zinc-950"
                type="checkbox"
                :disabled="isChunkJobRunning"
              />
              合并同级
            </label>
            <button
              data-testid="rechunk-button"
              class="h-9 rounded-lg bg-zinc-950 px-3 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:bg-zinc-200 disabled:text-zinc-400"
              type="button"
              :disabled="!parsedDocumentInfo || isChunkJobRunning"
              @click="handleRechunk"
            >
              重新分块
            </button>
          </div>
        </div>

        <div
          v-if="hasChunkPreview"
          data-testid="chunk-preview"
          class="mt-4 grid gap-2"
        >
          <article
            v-for="chunk in chunkItems"
            :key="chunk.id"
            data-testid="chunk-preview-item"
            class="rounded-lg border border-zinc-200 bg-white p-3 shadow-sm"
          >
            <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-500">
              <span>#{{ chunk.sequence_index + 1 }}</span>
              <span>{{ formatHeadingPath(chunk) }}</span>
              <span>{{ formatPageNumbers(chunk) }}</span>
              <span>{{ chunk.token_count ?? 0 }} tokens</span>
            </div>
            <p class="mt-2 whitespace-pre-wrap text-sm leading-6 text-zinc-800">
              {{ chunk.text || chunk.contextualized_text || "空分块" }}
            </p>
          </article>
          <p
            v-if="chunkItems.length === 0"
            data-testid="chunk-preview-empty"
            class="rounded-lg border border-dashed border-zinc-200 bg-white px-3 py-4 text-sm text-zinc-500"
          >
            暂无分块可预览
          </p>
        </div>
      </section>
    </div>

    <div
      data-testid="chat-composer"
      class="fixed bottom-0 left-0 right-0 z-20 border-t border-zinc-200/70 bg-zinc-50/90 px-3 py-3 backdrop-blur sm:px-4 sm:py-5"
    >
      <form
        class="mx-auto flex w-full max-w-3xl flex-col gap-2 rounded-2xl bg-white p-2 shadow-[0_10px_35px_rgba(15,23,42,0.12)] ring-1 ring-zinc-200 sm:p-3"
        @submit.prevent="handleSend"
      >
        <div
          v-if="selectedFile"
          data-testid="selected-file-chip"
          class="flex max-w-full items-center gap-2 self-start rounded-lg bg-zinc-100 px-3 py-1.5 text-sm text-zinc-700 ring-1 ring-zinc-200"
        >
          <span class="max-w-64 truncate">{{ selectedFile.name }}</span>
          <button
            data-testid="remove-attachment-button"
            class="flex size-5 items-center justify-center rounded-full text-zinc-500 transition hover:bg-zinc-200 hover:text-zinc-900"
            type="button"
            aria-label="移除附件"
            :disabled="isUploading"
            @click="removeSelectedFile"
          >
            x
          </button>
        </div>
        <p
          v-if="uploadStatus"
          data-testid="upload-status"
          class="px-1 text-sm text-zinc-500"
        >
          {{ uploadStatus }}
        </p>
        <div
          v-if="uploadedFileInfo && !isUploading"
          data-testid="parse-entry"
          class="flex items-center gap-3 self-start px-1"
        >
          <button
            v-if="canRetryParse"
            data-testid="parse-action-button"
            class="rounded-lg bg-zinc-950 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50"
            type="button"
            :disabled="isParsing"
            @click="handleParse"
          >
            重试解析
          </button>
          <span
            v-if="parseStatusText"
            data-testid="parse-status"
            class="text-sm text-zinc-500"
          >
            {{ parseStatusText }}
          </span>
        </div>
        <div class="flex items-end gap-2 sm:gap-3">
          <input
            ref="fileInputRef"
            data-testid="attachment-input"
            class="hidden"
            type="file"
            accept=".pdf,.md,.markdown,.txt,.docx,.pptx,application/pdf,text/markdown,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.presentationml.presentation"
            @change="handleFileChange"
          />
          <button
            data-testid="attachment-button"
            class="flex size-12 shrink-0 items-center justify-center rounded-xl text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-950 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-950 sm:size-14"
            type="button"
            aria-label="添加附件"
            :disabled="isUploading"
            @click="openFilePicker"
          >
            <svg
              class="size-5"
              aria-hidden="true"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path
                d="m21.4 11.6-8.5 8.5a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 1 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5"
              />
            </svg>
          </button>
          <textarea
            ref="textareaRef"
            v-model="message"
            data-testid="chat-input"
            class="max-h-48 min-h-12 flex-1 resize-none rounded-xl border-0 bg-transparent px-3 py-3 text-base leading-6 text-zinc-950 outline-none placeholder:text-zinc-400 focus:ring-0 sm:min-h-14"
            placeholder="请输入你的问题..."
            rows="1"
            @input="handleInput"
            @keydown="handleInputKeydown"
          />
          <button
            data-testid="send-button"
            class="flex size-12 shrink-0 items-center justify-center rounded-xl text-sm font-semibold transition disabled:cursor-not-allowed sm:size-14"
            :class="
              canSend
                ? 'bg-zinc-950 text-white shadow-sm hover:bg-zinc-800'
                : 'bg-zinc-200 text-zinc-400'
            "
            type="submit"
            :disabled="!canSend"
            aria-label="发送"
          >
            {{ isUploading ? "上传" : "发送" }}
          </button>
        </div>
      </form>
    </div>
  </section>
</template>
