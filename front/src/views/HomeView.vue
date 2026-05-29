<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from "vue"

import {
  createDocument,
  DocumentConflictError,
  listDocuments,
  type DocumentRecord,
} from "../api/documents"
import { uploadFile } from "../api/uploads"
import { useAppStore } from "../stores/app"
import { useUserStore } from "../stores/user"

const appStore = useAppStore()
const userStore = useUserStore()
const message = ref("")
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)
const isUploading = ref(false)
const uploadFeedback = ref<string | null>(null)
const documents = ref<DocumentRecord[]>([])
const isLoadingDocuments = ref(false)
const documentListError = ref<string | null>(null)
const isAccountDrawerOpen = ref(false)
const isSettingsModalOpen = ref(false)
const activeView = ref<"assistant" | "knowledge">("assistant")
const isLoggedOut = ref(false)
const librarySearch = ref("")
const activeLibraryFilter = ref<"all" | "image" | "file">("all")
const selectedDocumentIds = ref<Set<string>>(new Set())
const recentConversations = ref([
  {
    id: "recent-course",
    title: "课程资料问答",
    updatedAt: "今天 14:20",
  },
  {
    id: "recent-project",
    title: "项目文档梳理",
    updatedAt: "昨天 21:15",
  },
  {
    id: "recent-paper",
    title: "论文阅读记录",
    updatedAt: "05/27 10:30",
  },
])

const canSend = computed(
  () =>
    !isLoggedOut.value &&
    !isUploading.value &&
    (message.value.trim().length > 0 ||
      (selectedFile.value !== null && currentUser.value !== null)),
)
const currentUser = computed(() =>
  isLoggedOut.value ? null : userStore.currentUser,
)
const userLabel = computed(
  () =>
    currentUser.value?.display_name ??
    (isLoggedOut.value ? "未登录" : "当前用户未连接"),
)
const userInitial = computed(() => userLabel.value.trim().slice(0, 1) || "用")
const uploadStatus = computed(() => {
  if (uploadFeedback.value) {
    return uploadFeedback.value
  }

  if (isUploading.value) {
    return "上传中..."
  }

  if (!isLoggedOut.value && userStore.userError) {
    return "当前用户不可用，无法上传附件"
  }

  return null
})

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
}

const removeSelectedFile = () => {
  selectedFile.value = null
  uploadFeedback.value = null

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

const loadDocuments = async () => {
  if (isLoggedOut.value) {
    documents.value = []
    isLoadingDocuments.value = false
    documentListError.value = null
    return
  }

  isLoadingDocuments.value = true
  documentListError.value = null

  try {
    documents.value = await listDocuments()
  } catch (error) {
    documentListError.value =
      error instanceof Error ? error.message : "资料列表加载失败"
  } finally {
    isLoadingDocuments.value = false
  }
}

const documentStatusLabel = (document: DocumentRecord) =>
  document.status === "parsed" ? "已解析" : "解析失败"

const formatChunkCount = (count: number) => `${count} 个片段`

const formatCreatedAt = (value: string) =>
  new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value))

const documentSourceName = (document: DocumentRecord) =>
  document.source_file?.original_filename ?? document.title

const imageExtensions = [
  ".apng",
  ".avif",
  ".gif",
  ".jpeg",
  ".jpg",
  ".png",
  ".svg",
  ".webp",
]

const isImageDocument = (document: DocumentRecord) => {
  const sourceName = documentSourceName(document).toLowerCase()
  const contentType =
    document.source_content_type ?? document.source_file?.content_type

  return (
    contentType?.startsWith("image/") === true ||
    imageExtensions.some((extension) => sourceName.endsWith(extension))
  )
}

const documentTypeLabel = (document: DocumentRecord) => {
  const sourceName = documentSourceName(document).toLowerCase()
  const contentType =
    document.source_content_type ?? document.source_file?.content_type

  if (isImageDocument(document)) {
    return "IMG"
  }

  if (contentType === "application/pdf" || sourceName.endsWith(".pdf")) {
    return "PDF"
  }

  if (
    contentType ===
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document" ||
    sourceName.endsWith(".docx") ||
    sourceName.endsWith(".doc")
  ) {
    return "DOC"
  }

  if (contentType === "text/markdown" || sourceName.endsWith(".md")) {
    return "MD"
  }

  if (contentType === "text/plain" || sourceName.endsWith(".txt")) {
    return "TXT"
  }

  if (sourceName.endsWith(".ppt") || sourceName.endsWith(".pptx")) {
    return "PPT"
  }

  return "FILE"
}

const documentTypeClass = (document: DocumentRecord) => {
  const label = documentTypeLabel(document)

  if (label === "PDF") {
    return "border-red-100 bg-red-50 text-red-700"
  }

  if (label === "DOC") {
    return "border-blue-100 bg-blue-50 text-blue-700"
  }

  if (label === "MD" || label === "TXT") {
    return "border-emerald-100 bg-emerald-50 text-emerald-700"
  }

  if (label === "PPT") {
    return "border-orange-100 bg-orange-50 text-orange-700"
  }

  if (label === "IMG") {
    return "border-violet-100 bg-violet-50 text-violet-700"
  }

  return "border-zinc-200 bg-zinc-100 text-zinc-700"
}

const formatSizeNumber = (value: number) =>
  Number.isInteger(value) ? `${value}` : value.toFixed(2).replace(/\.?0+$/, "")

const formatFileSize = (document: DocumentRecord) => {
  const byteSize = document.source_file?.byte_size

  if (typeof byteSize !== "number" || Number.isNaN(byteSize)) {
    return "大小未知"
  }

  if (byteSize < 1024) {
    return `${byteSize} B`
  }

  if (byteSize < 1024 * 1024) {
    return `${formatSizeNumber(byteSize / 1024)} KB`
  }

  return `${formatSizeNumber(byteSize / 1024 / 1024)} MB`
}

const formatModifiedAt = (document: DocumentRecord) =>
  formatCreatedAt(document.updated_at ?? document.created_at)

const matchesLibraryFilter = (document: DocumentRecord) => {
  if (activeLibraryFilter.value === "all") {
    return true
  }

  if (activeLibraryFilter.value === "image") {
    return isImageDocument(document)
  }

  return !isImageDocument(document)
}

const filteredDocuments = computed(() => {
  const keyword = librarySearch.value.trim().toLowerCase()

  return documents.value.filter((document) => {
    if (!matchesLibraryFilter(document)) {
      return false
    }

    if (keyword.length === 0) {
      return true
    }

    return (
      document.title.toLowerCase().includes(keyword) ||
      documentSourceName(document).toLowerCase().includes(keyword)
    )
  })
})

const libraryFilterButtonClass = (filter: "all" | "image" | "file") =>
  activeLibraryFilter.value === filter
    ? "bg-zinc-100 text-zinc-950"
    : "text-zinc-500 hover:bg-zinc-50 hover:text-zinc-950"

const isDocumentSelected = (documentId: string) =>
  selectedDocumentIds.value.has(documentId)

const toggleDocumentSelection = (documentId: string) => {
  const nextSelectedIds = new Set(selectedDocumentIds.value)

  if (nextSelectedIds.has(documentId)) {
    nextSelectedIds.delete(documentId)
  } else {
    nextSelectedIds.add(documentId)
  }

  selectedDocumentIds.value = nextSelectedIds
}

const openSettingsModal = () => {
  isSettingsModalOpen.value = true
  isAccountDrawerOpen.value = false
}

const openKnowledgeLibrary = () => {
  activeView.value = "knowledge"
  isAccountDrawerOpen.value = false
}

const openAssistant = () => {
  activeView.value = "assistant"
}

const closeSettingsModal = () => {
  isSettingsModalOpen.value = false
}

const handleLogout = () => {
  isLoggedOut.value = true
  isAccountDrawerOpen.value = false
  isSettingsModalOpen.value = false
  activeView.value = "knowledge"
  documents.value = []
  librarySearch.value = ""
  activeLibraryFilter.value = "all"
  selectedDocumentIds.value = new Set()
  recentConversations.value = []
  message.value = ""
  uploadFeedback.value = null
  removeSelectedFile()
}

const setConflictFeedback = (error: DocumentConflictError) => {
  uploadFeedback.value = `${error.existingDocument.title} 已处理，${formatChunkCount(
    error.existingDocument.chunk_count,
  )}`
}

const processUploadedFile = async (
  uploadedFileId: string,
  originalFilename: string,
) => {
  try {
    const document = await createDocument(uploadedFileId)
    uploadFeedback.value = `${originalFilename} 上传成功，${documentStatusLabel(
      document,
    )} ${formatChunkCount(document.chunk_count)}`
  } catch (error) {
    if (error instanceof DocumentConflictError) {
      setConflictFeedback(error)
      return
    }

    throw error
  } finally {
    await loadDocuments()
  }
}

const retryDocument = async (document: DocumentRecord) => {
  if (isLoggedOut.value) {
    uploadFeedback.value = "当前用户不可用，无法处理资料"
    return
  }

  try {
    const processed = await createDocument(document.uploaded_file_id)
    uploadFeedback.value = `${processed.title} ${documentStatusLabel(
      processed,
    )} ${formatChunkCount(processed.chunk_count)}`
  } catch (error) {
    if (error instanceof DocumentConflictError) {
      setConflictFeedback(error)
      return
    }

    uploadFeedback.value =
      error instanceof Error ? error.message : "资料处理失败，请重试"
  } finally {
    await loadDocuments()
  }
}

const handleSend = async () => {
  if (!canSend.value || isUploading.value) {
    return
  }

  if (selectedFile.value) {
    if (!currentUser.value) {
      uploadFeedback.value = "当前用户不可用，无法上传附件"
      return
    }

    isUploading.value = true
    uploadFeedback.value = null

    try {
      const uploaded = await uploadFile(selectedFile.value)
      clearFileInput()
      await processUploadedFile(uploaded.id, uploaded.original_filename)
    } catch (error) {
      uploadFeedback.value =
        error instanceof Error ? error.message : "上传失败，请重试"
      return
    } finally {
      isUploading.value = false
    }
  }

  message.value = ""
  void resizeInput()
}

const handleInputKeydown = (event: KeyboardEvent) => {
  if (event.key !== "Enter" || event.shiftKey) {
    return
  }

  event.preventDefault()
  handleSend()
}

onMounted(() => {
  void appStore.refreshHealth()
  void userStore.loadCurrentUser()
  void loadDocuments()
  void resizeInput()
})
</script>

<template>
  <section
    data-testid="home-shell"
    class="relative flex h-screen overflow-hidden bg-white text-zinc-950"
  >
    <aside
      class="relative z-30 flex h-screen w-20 shrink-0 flex-col border-r border-zinc-200 bg-zinc-50 px-3 py-3 sm:w-72"
    >
      <div class="mb-5 flex items-center justify-center gap-2 sm:justify-start">
        <div
          class="flex size-8 items-center justify-center rounded-lg bg-zinc-950 text-sm font-semibold text-white"
        >
          k
        </div>
        <div class="hidden min-w-0 sm:block">
          <p class="text-sm font-semibold tracking-normal text-zinc-950">
            knowra
          </p>
          <p class="text-xs text-zinc-500">私有知识助手</p>
        </div>
      </div>

      <nav class="space-y-1 text-sm">
        <button
          type="button"
          class="flex w-full items-center justify-center rounded-md px-3 py-2 text-left font-medium transition hover:bg-zinc-100 sm:justify-between"
          :class="
            activeView === 'assistant'
              ? 'bg-zinc-100 text-zinc-950'
              : 'text-zinc-600'
          "
          @click="openAssistant"
        >
          <span class="hidden truncate sm:block">问答助手</span>
          <span class="text-xs text-zinc-400">Enter</span>
        </button>
        <button
          type="button"
          class="flex w-full items-center justify-center rounded-md px-3 py-2 text-left font-medium transition hover:bg-zinc-100 sm:justify-between"
          :class="
            activeView === 'knowledge'
              ? 'bg-zinc-100 text-zinc-950'
              : 'text-zinc-600'
          "
          @click="openKnowledgeLibrary"
        >
          <span class="hidden truncate sm:block">个人知识库</span>
          <span class="text-xs text-zinc-400">{{ documents.length }}</span>
        </button>
      </nav>

      <section
        data-testid="recent-conversations"
        class="mt-6 hidden min-h-0 flex-1 overflow-y-auto sm:block"
        aria-label="最近对话"
      >
        <div class="mb-3 flex items-center justify-between">
          <h2 class="text-xs font-semibold text-zinc-500">最近对话</h2>
        </div>
        <div v-if="recentConversations.length > 0" class="space-y-1">
          <button
            v-for="conversation in recentConversations"
            :key="conversation.id"
            type="button"
            class="block w-full rounded-md px-3 py-2 text-left transition hover:bg-zinc-100"
          >
            <span class="block truncate text-sm font-medium text-zinc-800">
              {{ conversation.title }}
            </span>
            <span class="mt-0.5 block text-xs text-zinc-400">
              {{ conversation.updatedAt }}
            </span>
          </button>
        </div>
        <p v-else class="rounded-md bg-zinc-50 px-3 py-4 text-sm text-zinc-500">
          暂无最近对话
        </p>
      </section>

      <div data-testid="sidebar-user-area" class="relative mt-auto">
        <div
          v-if="isAccountDrawerOpen"
          data-testid="account-drawer"
          class="absolute bottom-14 left-0 z-40 w-72 max-w-[calc(100vw-1.5rem)] rounded-xl border border-zinc-200 bg-white p-3 shadow-2xl"
        >
          <div class="mb-3 border-b border-zinc-100 pb-3">
            <div class="flex items-center gap-3">
              <div
                class="flex size-10 items-center justify-center rounded-full bg-zinc-950 text-sm font-semibold text-white"
              >
                {{ userInitial }}
              </div>
              <div class="min-w-0">
                <p class="truncate text-sm font-semibold text-zinc-950">
                  {{ userLabel }}
                </p>
                <p class="truncate text-xs text-zinc-500">
                  {{ currentUser?.email ?? "未登录" }}
                </p>
              </div>
            </div>
          </div>

          <button
            data-testid="settings-menu-item"
            type="button"
            class="flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm font-medium text-zinc-700 transition hover:bg-zinc-100"
            @click="openSettingsModal"
          >
            <span>设置</span>
            <span class="text-zinc-400">›</span>
          </button>
          <button
            data-testid="knowledge-library-menu-item"
            type="button"
            class="flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm font-medium text-zinc-700 transition hover:bg-zinc-100"
            @click="openKnowledgeLibrary"
          >
            <span>个人知识库</span>
            <span class="text-zinc-400">{{ documents.length }}</span>
          </button>
          <button
            data-testid="logout-menu-item"
            type="button"
            class="mt-2 flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm font-medium text-red-600 transition hover:bg-red-50"
            @click="handleLogout"
          >
            <span>退出登录</span>
            <span class="text-red-300">×</span>
          </button>
        </div>

        <button
          data-testid="user-avatar-button"
          type="button"
          class="flex h-12 w-full items-center justify-center gap-2 rounded-lg px-2 text-sm font-medium text-zinc-700 transition hover:bg-zinc-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-950 sm:justify-start"
          aria-label="用户菜单"
          :aria-expanded="isAccountDrawerOpen"
          @click="isAccountDrawerOpen = !isAccountDrawerOpen"
        >
          <span
            class="flex size-8 shrink-0 items-center justify-center rounded-full bg-zinc-950 text-sm font-semibold text-white"
          >
            {{ userInitial }}
          </span>
          <span class="hidden min-w-0 truncate sm:block">{{ userLabel }}</span>
        </button>
      </div>
    </aside>

    <div class="flex min-w-0 flex-1 flex-col bg-white">
      <header
        v-if="activeView === 'assistant'"
        class="flex h-14 shrink-0 items-center border-b border-zinc-200 bg-white px-4 sm:px-6"
      >
        <h1 class="text-base font-semibold tracking-normal text-zinc-950">
          knowra
        </h1>
      </header>

      <main
        v-if="activeView === 'assistant'"
        class="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 py-8 pb-36 sm:px-6 sm:py-12 sm:pb-40"
      >
        <div
          class="mx-auto grid w-full max-w-xl flex-1 place-items-center text-center"
        >
          <div>
            <p
              class="text-xl font-semibold tracking-normal text-zinc-900 sm:text-2xl"
            >
              今天想了解什么？
            </p>
            <p class="mt-3 text-sm leading-6 text-zinc-500 sm:text-base">
              输入问题后，knowra
              会围绕你的私有资料组织回答，并为后续引用来源展示保留空间。
            </p>
          </div>
        </div>
      </main>

      <main
        v-else
        data-testid="knowledge-library-view"
        class="grid min-h-0 flex-1 grid-rows-[auto_1fr] bg-zinc-50"
      >
        <div class="border-b border-zinc-200 bg-white px-4 py-3 sm:px-6">
          <div
            class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between"
          >
            <div>
              <p class="text-xs font-medium text-zinc-500">全部资源</p>
              <h2
                class="mt-1 text-xl font-semibold tracking-normal text-zinc-950"
              >
                个人知识库
              </h2>
            </div>

            <div
              data-testid="knowledge-library-toolbar"
              class="flex flex-col gap-2 sm:flex-row sm:items-center"
            >
              <label class="relative block min-w-0 sm:w-72">
                <span
                  class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400"
                  aria-hidden="true"
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
                    <circle cx="11" cy="11" r="8" />
                    <path d="m21 21-4.3-4.3" />
                  </svg>
                </span>
                <input
                  v-model="librarySearch"
                  data-testid="library-search-input"
                  class="h-10 w-full rounded-full border border-zinc-200 bg-white pl-9 pr-3 text-sm text-zinc-950 outline-none placeholder:text-zinc-400 focus:border-zinc-400 focus:ring-2 focus:ring-zinc-100"
                  type="search"
                  placeholder="搜索资料库"
                />
              </label>

              <button
                data-testid="library-upload-button"
                type="button"
                class="inline-flex h-10 items-center gap-2 rounded-full bg-zinc-950 px-4 text-sm font-medium text-white transition hover:bg-zinc-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-950 disabled:cursor-not-allowed disabled:bg-zinc-200 disabled:text-zinc-400"
                aria-label="上传资料"
                :disabled="isUploading || isLoggedOut"
                @click="openFilePicker"
              >
                <svg
                  class="size-4"
                  aria-hidden="true"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                >
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <path d="M17 8 12 3 7 8" />
                  <path d="M12 3v12" />
                </svg>
                <span>上传</span>
              </button>
            </div>
          </div>

          <div
            data-testid="library-filter-tabs"
            class="mt-4 flex flex-wrap items-center gap-1"
          >
            <button
              data-testid="library-filter-all"
              type="button"
              class="rounded-full px-3 py-1.5 text-sm font-medium transition"
              :class="libraryFilterButtonClass('all')"
              @click="activeLibraryFilter = 'all'"
            >
              全部
            </button>
            <button
              data-testid="library-filter-image"
              type="button"
              class="rounded-full px-3 py-1.5 text-sm font-medium transition"
              :class="libraryFilterButtonClass('image')"
              @click="activeLibraryFilter = 'image'"
            >
              图片
            </button>
            <button
              data-testid="library-filter-file"
              type="button"
              class="rounded-full px-3 py-1.5 text-sm font-medium transition"
              :class="libraryFilterButtonClass('file')"
              @click="activeLibraryFilter = 'file'"
            >
              文件
            </button>
            <div class="ml-auto flex items-center gap-2 text-xs text-zinc-500">
              <span>{{ filteredDocuments.length }} 项资源</span>
              <span>·</span>
              <span>按修改时间排序</span>
              <span v-if="isLoadingDocuments">· 加载中</span>
            </div>
          </div>
        </div>

        <section class="min-h-0 overflow-y-auto px-4 py-4 pb-36 sm:px-6 sm:pb-40">
          <p
            v-if="documentListError"
            data-testid="document-list-error"
            class="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
          >
            {{ documentListError }}
          </p>

          <div
            data-testid="document-list"
            class="min-h-full overflow-x-auto rounded-lg border border-zinc-200 bg-white"
          >
            <table class="w-full min-w-[760px] table-fixed text-left">
              <thead>
                <tr
                  data-testid="library-table-header"
                  class="border-b border-zinc-200 bg-zinc-50 text-xs font-medium text-zinc-500"
                >
                  <th class="w-14 px-4 py-3 font-medium"></th>
                  <th class="w-[44%] px-4 py-3 font-medium">名称</th>
                  <th class="w-[22%] px-4 py-3 font-medium">已修改 ↓</th>
                  <th class="w-[15%] px-4 py-3 font-medium">大小</th>
                  <th class="w-[15%] px-4 py-3 text-right font-medium">
                    操作
                  </th>
                </tr>
              </thead>
              <tbody class="divide-y divide-zinc-100">
                <tr
                  v-for="document in filteredDocuments"
                  :key="document.id"
                  :data-testid="`library-file-row-${document.id}`"
                  class="transition hover:bg-zinc-100 active:bg-zinc-100"
                  :class="isDocumentSelected(document.id) ? 'bg-zinc-100' : 'bg-white'"
                >
                  <td class="px-4 py-3 align-middle">
                    <label
                      class="relative inline-flex size-4 items-center justify-center"
                    >
                      <input
                        type="checkbox"
                        class="size-4 cursor-pointer appearance-none rounded-md border border-zinc-300 bg-white transition checked:border-zinc-950 checked:bg-zinc-950 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-950"
                        :data-testid="`library-file-select-${document.id}`"
                        :checked="isDocumentSelected(document.id)"
                        :aria-label="`选择 ${documentSourceName(document)}`"
                        @click.stop
                        @change="toggleDocumentSelection(document.id)"
                      />
                      <svg
                        v-if="isDocumentSelected(document.id)"
                        :data-testid="`library-file-check-${document.id}`"
                        class="pointer-events-none absolute size-3 text-white"
                        aria-hidden="true"
                        viewBox="0 0 16 16"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2.5"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                      >
                        <path d="M3.5 8.5 6.5 11.5 12.5 4.5" />
                      </svg>
                    </label>
                  </td>
                  <td class="px-4 py-3 align-middle">
                    <div class="flex min-w-0 items-center gap-3">
                      <div
                        class="flex size-10 shrink-0 items-center justify-center rounded-md border"
                        :class="documentTypeClass(document)"
                      >
                        <svg
                          v-if="isImageDocument(document)"
                          class="size-5"
                          aria-hidden="true"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          stroke-width="2"
                          stroke-linecap="round"
                          stroke-linejoin="round"
                        >
                          <rect x="3" y="3" width="18" height="18" rx="2" />
                          <circle cx="9" cy="9" r="2" />
                          <path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21" />
                        </svg>
                        <svg
                          v-else
                          class="size-5"
                          aria-hidden="true"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          stroke-width="2"
                          stroke-linecap="round"
                          stroke-linejoin="round"
                        >
                          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                          <path d="M14 2v6h6" />
                        </svg>
                      </div>

                      <div class="min-w-0">
                        <div class="flex min-w-0 items-center gap-2">
                          <p class="truncate text-sm font-semibold text-zinc-950">
                            {{ documentSourceName(document) }}
                          </p>
                          <span
                            class="shrink-0 rounded-md px-2 py-0.5 text-xs font-semibold"
                            :class="documentTypeClass(document)"
                          >
                            {{ documentTypeLabel(document) }}
                          </span>
                        </div>
                        <div
                          class="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-zinc-400"
                        >
                          <span
                            :class="
                              document.status === 'parsed'
                                ? 'text-emerald-700'
                                : 'text-red-600'
                            "
                          >
                            {{ documentStatusLabel(document) }}
                          </span>
                          <span>{{ formatChunkCount(document.chunk_count) }}</span>
                          <button
                            v-if="document.status === 'failed'"
                            data-testid="retry-document-button"
                            type="button"
                            class="rounded-md border border-zinc-200 px-2 py-0.5 text-xs font-medium text-zinc-700 transition hover:bg-zinc-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-950"
                            @click="retryDocument(document)"
                          >
                            重试
                          </button>
                        </div>
                        <p
                          v-if="
                            document.status === 'failed' &&
                            document.error_message
                          "
                          class="mt-1 truncate text-xs text-red-600"
                        >
                          {{ document.error_message }}
                        </p>
                      </div>
                    </div>
                  </td>
                  <td class="px-4 py-3 align-middle text-sm text-zinc-500">
                    {{ formatModifiedAt(document) }}
                  </td>
                  <td class="px-4 py-3 align-middle text-sm text-zinc-500">
                    {{ formatFileSize(document) }}
                  </td>
                  <td class="px-4 py-3 align-middle">
                    <div class="flex items-center justify-end gap-1">
                      <button
                        type="button"
                        class="flex size-8 items-center justify-center rounded-md text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-950 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-950"
                        :data-testid="`library-file-download-${document.id}`"
                        :aria-label="`下载 ${documentSourceName(document)}`"
                      >
                        <svg
                          class="size-4"
                          aria-hidden="true"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          stroke-width="2"
                          stroke-linecap="round"
                          stroke-linejoin="round"
                        >
                          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                          <path d="M7 10l5 5 5-5" />
                          <path d="M12 15V3" />
                        </svg>
                      </button>
                      <button
                        type="button"
                        class="flex size-8 items-center justify-center rounded-md text-zinc-500 transition hover:bg-zinc-100 hover:text-red-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-950"
                        :data-testid="`library-file-delete-${document.id}`"
                        :aria-label="`删除 ${documentSourceName(document)}`"
                      >
                        <svg
                          class="size-4"
                          aria-hidden="true"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          stroke-width="2"
                          stroke-linecap="round"
                          stroke-linejoin="round"
                        >
                          <path d="M3 6h18" />
                          <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                          <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                          <path d="M10 11v6" />
                          <path d="M14 11v6" />
                        </svg>
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>

            <div
              v-if="!isLoadingDocuments && filteredDocuments.length === 0"
              data-testid="knowledge-empty-state"
              class="grid min-h-64 place-items-center px-4 py-10 text-center"
            >
              <div>
                <p class="text-sm font-semibold text-zinc-800">
                  {{
                    documents.length === 0
                      ? "个人知识库为空"
                      : "没有匹配的资源"
                  }}
                </p>
                <p class="mt-2 text-sm text-zinc-500">
                  {{
                    documents.length === 0
                      ? "上传 PDF、Word、TXT 或 Markdown 资料后会在这里集中管理。"
                      : "调整搜索关键词或分类筛选后再试。"
                  }}
                </p>
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>

    <div
      v-if="isSettingsModalOpen"
      class="fixed inset-0 z-50 grid place-items-center bg-zinc-950/30 px-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="settings-modal-title"
    >
      <section
        data-testid="settings-modal"
        class="w-full max-w-md rounded-lg bg-white p-5 shadow-2xl"
      >
        <div class="flex items-center justify-between gap-3">
          <h2
            id="settings-modal-title"
            class="text-lg font-semibold tracking-normal text-zinc-950"
          >
            个人信息
          </h2>
          <button
            data-testid="settings-modal-close"
            type="button"
            class="flex size-8 items-center justify-center rounded-md text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-950"
            aria-label="关闭设置"
            @click="closeSettingsModal"
          >
            ×
          </button>
        </div>
        <dl class="mt-5 divide-y divide-zinc-100 text-sm">
          <div class="grid grid-cols-[5rem_minmax(0,1fr)] gap-3 py-3">
            <dt class="text-zinc-500">用户名</dt>
            <dd class="truncate font-medium text-zinc-950">{{ userLabel }}</dd>
          </div>
          <div class="grid grid-cols-[5rem_minmax(0,1fr)] gap-3 py-3">
            <dt class="text-zinc-500">邮箱</dt>
            <dd class="truncate text-zinc-800">
              {{ currentUser?.email ?? "未设置" }}
            </dd>
          </div>
          <div class="grid grid-cols-[5rem_minmax(0,1fr)] gap-3 py-3">
            <dt class="text-zinc-500">状态</dt>
            <dd class="text-zinc-800">
              {{ currentUser?.status ?? "logged_out" }}
            </dd>
          </div>
          <div class="grid grid-cols-[5rem_minmax(0,1fr)] gap-3 py-3">
            <dt class="text-zinc-500">创建时间</dt>
            <dd class="text-zinc-800">
              {{
                currentUser?.created_at
                  ? formatCreatedAt(currentUser.created_at)
                  : "暂无"
              }}
            </dd>
          </div>
        </dl>
      </section>
    </div>

    <div
      data-testid="chat-composer"
      class="fixed bottom-0 left-20 right-0 z-20 border-t border-zinc-200/70 bg-white/90 px-3 py-3 backdrop-blur sm:left-72 sm:px-4 sm:py-5"
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
        <div class="flex items-end gap-2 sm:gap-3">
          <input
            ref="fileInputRef"
            data-testid="attachment-input"
            class="hidden"
            type="file"
            @change="handleFileChange"
          />
          <button
            data-testid="attachment-button"
            class="flex size-12 shrink-0 items-center justify-center rounded-xl text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-950 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-950 sm:size-14"
            type="button"
            aria-label="添加附件"
            :disabled="isUploading || isLoggedOut"
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
            :disabled="isLoggedOut"
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
