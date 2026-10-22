<script setup lang="ts">
/**
 * WelcomeView — 空对话的起手页：「上传资料 → 提问 → 核对来源」。
 * 推荐问题只填入输入框（pick-suggestion），由用户确认后再发送。
 */
withDefaults(defineProps<{ canUpload?: boolean }>(), { canUpload: true })

const emit = defineEmits<{
  (e: "upload"): void
  (e: "pick-suggestion", text: string): void
}>()

const SUGGESTIONS = [
  "总结这些资料的核心观点",
  "列出资料中的关键概念并逐一解释",
  "资料里有哪些结论需要特别注意前提条件？",
]
</script>

<template>
  <div data-testid="welcome-view" class="flex flex-col py-10 sm:py-16">
    <div class="flex items-center gap-3">
      <span
        data-testid="welcome-icon"
        class="flex size-9 items-center justify-center rounded-lg bg-brand-700 font-display text-lg font-semibold text-white"
        aria-hidden="true"
        >知</span
      >
      <span class="text-xs font-semibold tracking-[0.12em] text-ink-faint"
        >知寻 · KNOWRA</span
      >
    </div>

    <h1
      class="mt-6 font-display text-[1.75rem] leading-tight font-semibold text-balance text-ink sm:text-[2.125rem]"
    >
      今天想了解什么？
    </h1>
    <p
      data-testid="welcome-subtitle"
      class="mt-3 max-w-xl text-[15px] leading-relaxed text-ink-muted"
    >
      上传资料后开始提问。知寻会依据你自己的资料作答，并在每个回答下方列出引用的原文片段。
    </p>

    <ol
      class="mt-8 grid gap-px overflow-hidden rounded-[var(--radius-card)] border border-line bg-line sm:grid-cols-3"
    >
      <li
        data-testid="welcome-step"
        class="flex flex-col gap-1.5 bg-surface p-4"
      >
        <span class="flex items-center gap-2 text-sm font-semibold text-ink">
          <span
            class="flex size-5 items-center justify-center rounded-full bg-brand-700 text-[11px] text-white tabular-nums"
            >1</span
          >
          上传资料
        </span>
        <span class="text-[13px] leading-relaxed text-ink-muted"
          >讲义、论文、笔记或项目文档。</span
        >
        <button
          type="button"
          data-testid="welcome-upload"
          :disabled="!canUpload"
          class="mt-1.5 inline-flex w-fit items-center gap-1.5 rounded-[var(--radius-button)] bg-brand-700 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-brand-800"
          @click="canUpload && emit('upload')"
        >
          <svg
            class="size-4"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.75"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M12 16V4M6 10l6-6 6 6M4 20h16" />
          </svg>
          上传资料
        </button>
        <p v-if="!canUpload" class="text-xs text-ink-muted">
          只读账号不能上传或处理资料
        </p>
      </li>
      <li
        data-testid="welcome-step"
        class="flex flex-col gap-1.5 bg-surface p-4"
      >
        <span class="flex items-center gap-2 text-sm font-semibold text-ink">
          <span
            class="flex size-5 items-center justify-center rounded-full border border-brand-600 text-[11px] text-brand-700 tabular-nums"
            >2</span
          >
          提问
        </span>
        <span class="text-[13px] leading-relaxed text-ink-muted"
          >用自然语言描述你想弄清楚的问题。</span
        >
      </li>
      <li
        data-testid="welcome-step"
        class="flex flex-col gap-1.5 bg-surface p-4"
      >
        <span class="flex items-center gap-2 text-sm font-semibold text-ink">
          <span
            class="flex size-5 items-center justify-center rounded-full border border-cite/60 text-[11px] text-cite tabular-nums"
            >3</span
          >
          核对来源
        </span>
        <span class="text-[13px] leading-relaxed text-ink-muted"
          >回答下方列出出处与原文，点开即可对照。</span
        >
      </li>
    </ol>

    <div class="mt-8">
      <p class="text-xs font-semibold tracking-[0.08em] text-ink-faint">
        试着问
      </p>
      <ul class="mt-2 flex flex-col">
        <li
          v-for="text in SUGGESTIONS"
          :key="text"
          class="border-b border-line last:border-b-0"
        >
          <button
            type="button"
            data-testid="welcome-suggestion"
            class="group flex w-full items-center justify-between gap-3 py-2.5 text-left text-[15px] text-ink transition-colors hover:text-brand-700"
            @click="emit('pick-suggestion', text)"
          >
            <span>{{ text }}</span>
            <svg
              class="size-4 shrink-0 text-ink-faint transition-transform group-hover:translate-x-0.5 group-hover:text-brand-700"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.75"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <path d="M5 12h14M13 6l6 6-6 6" />
            </svg>
          </button>
        </li>
      </ul>
      <p class="mt-2 text-xs text-ink-faint">
        点击后填入输入框，可修改后再发送。
      </p>
    </div>
  </div>
</template>
