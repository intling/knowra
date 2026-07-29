<script setup lang="ts">
defineProps<{
  /** 用户消息文本内容 */
  content: string
  /** 本条消息附带的已上传文件名称列表 */
  fileNames?: string[]
}>()
</script>

<template>
  <div
    data-testid="user-message"
    class="flex justify-end"
  >
    <div
      data-testid="user-message-bubble"
      class="max-w-[85%] space-y-2 rounded-xl rounded-br-sm bg-brand-700 px-4 py-2.5 text-sm leading-6 text-white"
    >
      <!-- 附带的文件标签 -->
      <div
        v-if="fileNames && fileNames.length > 0"
        data-testid="user-message-files"
        class="flex flex-wrap gap-1.5"
      >
        <span
          v-for="name in fileNames"
          :key="name"
          data-testid="user-message-file-chip"
          class="inline-flex items-center gap-1 rounded-md bg-white/15 px-2 py-0.5 text-xs"
        >
          <svg
            class="size-3 shrink-0"
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
          {{ name }}
        </span>
      </div>

      <!-- 消息文本（仅当内容非空时展示） -->
      <p v-if="content">{{ content }}</p>
    </div>
  </div>
</template>
