<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue"
import { marked } from "marked"
import DOMPurify from "dompurify"

import type { AnswerTokens, SearchResponse } from "../api/search"

const props = withDefaults(
  defineProps<{
    answerMode?: SearchResponse["answer_mode"]
    answer?: string
    streaming?: boolean
    answerIncomplete?: boolean
    answerTokens?: AnswerTokens | null
    chatModel?: string | null
    totalResults?: number
    documentCount?: number
    generationError?: string | null
  }>(),
  {
    answerMode: undefined,
    answer: "",
    streaming: false,
    answerIncomplete: false,
    answerTokens: null,
    chatModel: null,
    totalResults: 0,
    documentCount: 0,
    generationError: null,
  },
)

const copyLabel = ref("复制")
const answerContentRef = ref<HTMLElement | null>(null)

const renderedMarkdown = computed(() => {
  if (!props.answer) return ""
  const raw = marked.parse(props.answer, { async: false }) as string
  return DOMPurify.sanitize(raw)
})

const tokenDetail = computed(() => {
  const t = props.answerTokens
  if (!t) return ""
  return `提示词 ${t.prompt_tokens.toLocaleString()} + 生成 ${t.completion_tokens.toLocaleString()} = ${t.total_tokens.toLocaleString()} tokens（prompt ${t.prompt_tokens} / completion ${t.completion_tokens}）`
})

const isDegraded = computed(
  () =>
    props.generationError !== null &&
    props.generationError !== "Chat generation is disabled",
)

async function handleCopy() {
  try {
    await navigator.clipboard.writeText(props.answer)
    copyLabel.value = "已复制"
    setTimeout(() => {
      copyLabel.value = "复制"
    }, 2000)
  } catch {
    copyLabel.value = "复制失败"
    setTimeout(() => {
      copyLabel.value = "复制"
    }, 2000)
  }
}

// ── Code block copy buttons ──

/** Find all <pre> elements inside the rendered answer and attach copy buttons. */
function attachCodeCopyButtons() {
  if (!answerContentRef.value) return

  const preElements = answerContentRef.value.querySelectorAll("pre")
  preElements.forEach((pre) => {
    // Avoid attaching twice (e.g. after HMR)
    if (pre.querySelector(".code-copy-btn")) return

    const wrapper = document.createElement("div")
    wrapper.className = "code-block-wrapper"

    // Wrap the <pre> in a relative-positioned container
    pre.parentNode?.insertBefore(wrapper, pre)
    wrapper.appendChild(pre)

    // Create copy button
    const btn = document.createElement("button")
    btn.className = "code-copy-btn"
    btn.setAttribute("aria-label", "复制代码")
    btn.innerHTML = `
      <svg class="code-copy-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
      </svg>
    `
    btn.innerHTML += '<span class="code-copy-label">复制</span>'

    btn.addEventListener("click", async () => {
      const code = pre.querySelector("code")
      const text = code ? code.textContent || "" : pre.textContent || ""
      try {
        await navigator.clipboard.writeText(text)
        btn.classList.add("copied")
        btn.setAttribute("aria-label", "已复制")
        const label = btn.querySelector(".code-copy-label")
        if (label) label.textContent = "已复制"
        setTimeout(() => {
          btn.classList.remove("copied")
          btn.setAttribute("aria-label", "复制代码")
          if (label) label.textContent = "复制"
        }, 1500)
      } catch {
        // Silently fail — clipboard may not be available
      }
    })

    wrapper.appendChild(btn)
  })
}

/** Remove all code copy buttons and their wrappers before re-attaching. */
function removeCodeCopyButtons() {
  if (!answerContentRef.value) return

  const wrappers = answerContentRef.value.querySelectorAll(
    ".code-block-wrapper",
  )
  wrappers.forEach((wrapper) => {
    const pre = wrapper.querySelector("pre")
    if (pre && wrapper.parentNode) {
      wrapper.parentNode.insertBefore(pre, wrapper)
    }
    wrapper.remove()
  })
}

// Watch for content changes and attach buttons after DOM update
watch([renderedMarkdown, () => props.streaming], async () => {
  await nextTick()
  removeCodeCopyButtons()
  if (!props.streaming) attachCodeCopyButtons()
})

onMounted(async () => {
  await nextTick()
  if (!props.streaming) attachCodeCopyButtons()
})

onUnmounted(() => {
  removeCodeCopyButtons()
})
</script>

<template>
  <article data-testid="answer-panel" :aria-busy="streaming" class="flex min-w-0 gap-3 sm:gap-4">
    <!-- 「知」字印章：标识这是知寻基于资料给出的回答 -->
    <span
      class="mt-0.5 flex size-7 shrink-0 select-none items-center justify-center rounded-md bg-brand-700 font-display text-sm font-semibold text-white"
      aria-hidden="true"
      >知</span
    >

    <div class="min-w-0 flex-1">
      <h3 class="sr-only">AI 回答{{ chatModel ? `（${chatModel}）` : "" }}</h3>
      <p
        v-if="!generationError && (streaming || answer)"
        data-testid="streaming-status"
        role="status"
        aria-live="polite"
        :class="streaming ? 'mb-3 flex items-center gap-2 text-xs text-ink-muted' : 'sr-only'"
      >
        <span v-if="streaming" aria-hidden="true" class="streaming-dot size-1.5 rounded-full bg-brand-600" />
        {{ streaming ? "正在生成回答…" : answerIncomplete ? "回答尚未完成" : "回答生成完成" }}
      </p>

      <div
        v-if="isDegraded"
        data-testid="answer-degraded"
        class="rounded-[var(--radius-button)] border-l-2 border-amber-500 bg-amber-50/70 px-3.5 py-2.5"
      >
        <p class="text-sm font-medium text-amber-900">AI 回答生成失败</p>
        <p class="mt-0.5 text-xs text-amber-800 [overflow-wrap:anywhere]">{{ generationError }}</p>
        <p class="mt-1.5 text-xs text-amber-700">请稍后重试。<template v-if="totalResults > 0">也可核对下方资料原文。</template></p>
      </div>

      <div
        v-else-if="generationError === 'Chat generation is disabled'"
        data-testid="answer-disabled"
        class="rounded-[var(--radius-button)] border-l-2 border-line-strong bg-paper-deep px-3.5 py-2.5"
      >
        <p class="text-sm text-ink-muted">
          {{ answer || "AI 回答生成功能未启用，请联系管理员配置对话模型。" }}
        </p>
      </div>

      <template v-else-if="answer || streaming">
        <div
          v-if="answerIncomplete"
          data-testid="answer-incomplete"
          role="status"
          class="mb-3 rounded-[var(--radius-button)] border-l-2 border-amber-500 bg-amber-50/70 px-3.5 py-2.5"
        >
          <p class="text-sm font-medium text-amber-900">回答尚未完成</p>
          <p class="mt-1 text-xs text-amber-800">本次生成提前结束，以下保留已生成的内容。你可以缩小问题范围，或继续提问以补充剩余内容。</p>
        </div>
        <!-- eslint-disable vue/no-v-html -->
        <div
          v-if="answer"
          ref="answerContentRef"
          data-testid="answer-content"
          class="prose-knowra answer-reveal"
          v-html="renderedMarkdown"
        ></div>
        <!-- eslint-enable vue/no-v-html -->
        <span
          v-if="streaming"
          data-testid="streaming-cursor"
          aria-hidden="true"
          class="streaming-cursor mt-1 inline-block h-4 w-0.5 rounded-full bg-brand-600 align-middle"
        />

        <div class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-ink-faint">
          <button
            data-testid="copy-answer-button"
            class="-ml-1.5 inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-ink-muted transition-colors hover:bg-paper-deep hover:text-ink"
            type="button"
            :disabled="!answer"
            @click="handleCopy"
          >
            <svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <rect x="9" y="9" width="12" height="12" rx="2" />
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
            </svg>
            {{ copyLabel }}
          </button>
          <span v-if="!answerMode || answerMode === 'rag' || answerMode === 'summary'" data-testid="citation-stats" class="tabular-nums">
            引用 {{ totalResults }} 个分块 · 来自 {{ documentCount }} 个文档
          </span>
          <span v-if="answerMode === 'general'" class="text-ink-muted">基于通用知识</span>
          <span v-if="answerTokens && answerMode !== 'clarification'" data-testid="token-stats" class="tabular-nums" :title="tokenDetail">
            <span data-testid="token-total">{{ answerTokens.total_tokens.toLocaleString() }} tokens</span>
            <span class="sr-only">，{{ tokenDetail }}</span>
          </span>
        </div>
      </template>

      <p v-else class="py-2 text-sm text-ink-faint">AI 未生成回答</p>
    </div>
  </article>
</template>


<style scoped>
@media (prefers-reduced-motion: no-preference) {
  .answer-reveal {
    animation: answer-reveal 180ms ease-out;
  }
  .streaming-dot {
    animation: generation-breathe 1.6s ease-in-out infinite;
  }
  .streaming-cursor {
    animation: generation-breathe 1s ease-in-out infinite;
  }
}

@keyframes answer-reveal {
  from { opacity: 0; transform: translateY(3px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes generation-breathe {
  50% { opacity: 0.35; }
}
</style>
