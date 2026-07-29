<script setup lang="ts">
/**
 * ChatTopNav — 聊天区域顶部导航栏
 *
 * 位于消息流上方、右侧主区域顶部，展示当前使用的 AI 模型名称。
 * 视觉上与项目「精密仪器」设计语言一致：克制、清晰、不抢眼。
 * 模型名称靠近内容区左侧，作为静默的参考信息而非主导元素。
 */
defineProps<{
  /** 当前对话模型名称，如 "deepseek-chat"、"gpt-4o" 等 */
  modelName?: string | null
}>()
</script>

<template>
  <div
    class="flex h-11 shrink-0 items-center border-neutral-100"
  >
    <div class="w-full max-w-3xl flex items-center px-4 sm:px-6">
      <!-- 模型标识 — 左对齐，安静地标注当前模型 -->
      <span
        v-if="modelName"
        class="text-base font-medium tracking-wide text-neutral-400"
      >
        {{ modelName }}
      </span>
      <span
        v-else
        class="text-xs text-neutral-300"
      >
        —
      </span>
    </div>
  </div>
</template>
