<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue"
import { marked } from "marked"
import DOMPurify from "dompurify"

import type { AnswerTokens } from "../api/search"

const props = withDefaults(
  defineProps<{
    answer?: string
    answerTokens?: AnswerTokens | null
    chatModel?: string | null
    totalResults?: number
    documentCount?: number
    generationError?: string | null
  }>(),
  {
    answer: "",
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

const isDegraded = computed(
  () => props.generationError !== null
    && props.generationError !== "Chat generation is disabled"
    && (!props.answer || props.answer.length === 0),
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

  const wrappers = answerContentRef.value.querySelectorAll(".code-block-wrapper")
  wrappers.forEach((wrapper) => {
    const pre = wrapper.querySelector("pre")
    if (pre && wrapper.parentNode) {
      wrapper.parentNode.insertBefore(pre, wrapper)
    }
    wrapper.remove()
  })
}

// Watch for content changes and attach buttons after DOM update
watch(renderedMarkdown, async () => {
  await nextTick()
  removeCodeCopyButtons()
  attachCodeCopyButtons()
})

onMounted(async () => {
  await nextTick()
  attachCodeCopyButtons()
})

onUnmounted(() => {
  removeCodeCopyButtons()
})
</script>

<template>
  <div>
    <!-- Header -->
    <div
      class="flex flex-wrap items-center justify-between gap-2 pb-3"
    >
      <h3 class="font-display text-sm font-semibold text-neutral-700">
        <span class="mr-1.5" aria-hidden="true">🤖</span>AI 回答
      </h3>
      <div class="flex items-center gap-2">
        <span
          v-if="chatModel"
          class="rounded-full bg-neutral-100 px-2 py-0.5 text-xs text-neutral-500"
        >
          {{ chatModel }}
        </span>
        <button
          data-testid="copy-answer-button"
          class="rounded-md border border-neutral-200 px-2.5 py-1 text-xs text-neutral-500 transition hover:border-neutral-400 hover:text-neutral-700"
          type="button"
          :disabled="!answer"
          @click="handleCopy"
        >
          {{ copyLabel }}
        </button>
      </div>
    </div>

    <!-- Degraded state: generation error without answer -->
    <div
      v-if="isDegraded"
      data-testid="answer-degraded"
      class="py-2"
    >
      <div class="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
        <p class="text-sm font-medium text-amber-800">AI 回答生成失败</p>
        <p class="mt-1 text-xs text-amber-600">
          {{ generationError }}
        </p>
        <p class="mt-2 text-xs text-amber-500">
          以下为检索到的相关内容，您仍可查看检索结果了解上下文。
        </p>
      </div>
    </div>

    <!-- Chat disabled state -->
    <div
      v-else-if="generationError === 'Chat generation is disabled'"
      data-testid="answer-disabled"
      class="py-2"
    >
      <div class="rounded-lg border border-neutral-200 bg-neutral-50 px-4 py-3">
        <p class="text-sm text-neutral-600">
          {{ answer || "AI 回答生成功能未启用，请联系管理员配置对话模型。" }}
        </p>
      </div>
    </div>

    <!-- Answer content -->
    <div
      v-else-if="answer"
    >
      <!-- eslint-disable vue/no-v-html -->
      <div
        ref="answerContentRef"
        data-testid="answer-content"
        class="prose prose-sm prose-knowra"
        v-html="renderedMarkdown"
      ></div>
      <!-- eslint-enable vue/no-v-html -->

      <!-- Stats footer -->
      <div
        class="mt-4 flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-neutral-100 pt-3 text-xs text-neutral-400"
      >
        <!-- Citation stats -->
        <span data-testid="citation-stats" class="inline-flex items-center gap-1">
          <svg class="size-3.5" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" stroke-linecap="round" />
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" stroke-linecap="round" />
          </svg>
          引用 {{ totalResults }} 个分块 · 来自 {{ documentCount }} 个文档
        </span>

        <!-- Token stats -->
        <span
          v-if="answerTokens"
          data-testid="token-stats"
          class="inline-flex items-center gap-1"
        >
          <svg class="size-3.5" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 6v6l4 2" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          Token: {{ answerTokens.prompt_tokens }} prompt + {{ answerTokens.completion_tokens }} completion = {{ answerTokens.total_tokens }} total
        </span>
      </div>
    </div>

    <!-- Empty state: no answer yet -->
    <div
      v-else
      class="flex items-center justify-center py-10"
    >
      <p class="text-sm text-neutral-400">等待 AI 回答生成...</p>
    </div>
  </div>
</template>
