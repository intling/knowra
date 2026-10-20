<script setup lang="ts">
/**
 * RetrievalDetails — 把查询改写、检索结果、提示词预览收纳进默认折叠的「检索详情」。
 * 三个子面板保持各自的折叠状态，因此诊断区是两级展开。
 */
import { computed, ref } from "vue"

import type { SearchResponse } from "../../api/search"
import { uniqueId } from "../../shared/a11y/focus"
import PromptPreview from "../PromptPreview.vue"
import ResultsPanel from "../ResultsPanel.vue"
import RewritePanel from "../RewritePanel.vue"

const props = defineProps<{
  response: SearchResponse
}>()

const isOpen = ref(false)
const bodyId = uniqueId("retrieval-details")

const resultCount = computed(() => props.response.results.length)
const elapsed = computed(() => {
  const ms = props.response.search_time_ms
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`
})
const hasRewrite = computed(() => props.response.rewrite_info !== null)
const hasPrompt = computed(() => props.response.prompt_messages.length > 0)
const hasResults = computed(() => resultCount.value > 0)
</script>

<template>
  <div data-testid="retrieval-details" class="min-w-0 overflow-hidden rounded-[var(--radius-card)] border border-line bg-paper-deep/60">
    <button
      type="button"
      data-testid="retrieval-details-toggle"
      class="flex w-full items-center justify-between gap-3 px-3.5 py-2.5 text-left transition-colors hover:bg-paper-deep"
      :aria-expanded="isOpen"
      :aria-controls="bodyId"
      @click="isOpen = !isOpen"
    >
      <span class="flex min-w-0 flex-wrap items-baseline gap-x-2 text-xs text-ink-faint">
        <span class="font-semibold tracking-[0.06em] text-ink-muted">检索详情</span>
        <span class="tabular-nums">{{ resultCount }} 个片段 · {{ elapsed }}</span>
      </span>
      <svg
        class="size-4 shrink-0 text-ink-faint transition-transform"
        :class="{ 'rotate-180': isOpen }"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.75"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <path d="m6 9 6 6 6-6" />
      </svg>
    </button>

    <div v-if="isOpen" :id="bodyId" class="border-t border-line bg-surface">
      <RewritePanel v-if="hasRewrite && response.rewrite_info" :rewrite-info="response.rewrite_info" variant="flat" />
      <ResultsPanel
        v-if="hasResults"
        variant="flat"
        :results="response.results"
        :searched-document-count="response.searched_document_count"
        :total-searched="response.total_searched"
        :search-time-ms="response.search_time_ms"
      />
      <PromptPreview v-if="hasPrompt" variant="flat" :messages="response.prompt_messages" />
    </div>
  </div>
</template>
