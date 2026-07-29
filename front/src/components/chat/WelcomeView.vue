<script setup lang="ts">
/**
 * WelcomeView — 空状态欢迎页
 *
 * 当用户没有活跃对话时显示。
 * 用户发送第一条消息后，此视图由 ChatArea 替换为消息流视图。
 *
 * 视觉签名：蓝色 Logo 标记 + Newsreader 衬线标题排版，
 * 传达知识工具的专业气质。
 */
</script>

<template>
  <div
    data-testid="welcome-view"
    class="flex flex-1 flex-col items-center justify-center px-6 py-16 text-center"
  >
    <!-- Logo 标记 — 品牌签名元素 -->
    <div
      data-testid="welcome-icon"
      class="relative mb-2 flex size-20 items-center justify-center"
      aria-hidden="true"
    >
      <!-- 外层柔和光晕 -->
      <div
        class="absolute inset-0 rounded-3xl bg-brand-100/60 blur-xl"
      />
      <!-- 内层 Logo 容器 -->
      <div
        class="relative flex size-16 items-center justify-center rounded-2xl brand-gradient shadow-lg shadow-brand-200/30 ring-1 ring-white/20"
      >
        <svg
          class="size-8 text-white"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M12 2L2 7l10 5 10-5-10-5z" />
          <path d="M2 17l10 5 10-5" />
          <path d="M2 12l10 5 10-5" />
        </svg>
      </div>
    </div>

    <!-- 欢迎语主标题 — Newsreader 衬线体，学术分量 -->
    <h1 class="font-display mt-6 text-2xl font-semibold tracking-tight text-neutral-900 sm:text-3xl">
      今天想了解什么？
    </h1>

    <!-- 引导副标题 — 安静的功能说明 -->
    <p
      data-testid="welcome-subtitle"
      class="mt-3 max-w-md text-sm leading-relaxed text-neutral-400"
    >
      上传资料后开始提问，AI 将基于你的知识库内容
      <br />
      生成带来源引用的回答。
    </p>

  </div>
</template>

<style scoped>
/* ── 欢迎页淡入动画 — 仅页面加载时触发一次 ── */
.welcome-fade-enter-active {
  transition: opacity 0.6s ease-out, transform 0.6s ease-out;
}
.welcome-fade-enter-from {
  opacity: 0;
  transform: translateY(12px);
}
</style>
