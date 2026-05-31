<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from "vue"

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

const handleSend = async () => {
  if (!canSend.value || isUploading.value) {
    return
  }

  if (selectedFile.value) {
    if (!userStore.currentUser) {
      uploadFeedback.value = "当前用户不可用，无法上传附件"
      return
    }

    isUploading.value = true
    uploadFeedback.value = null

    try {
      const uploaded = await uploadFile(selectedFile.value)
      uploadFeedback.value = `${uploaded.original_filename} 上传成功`
      clearFileInput()
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
