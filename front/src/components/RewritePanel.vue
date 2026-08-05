<script setup lang="ts">
import { ref } from "vue"
import type { RewriteInfo } from "../api/search"

const props = defineProps<{
  rewriteInfo: RewriteInfo
}>()

// ── Collapse toggle ──
const isExpanded = ref(false)

function toggleExpand() {
  isExpanded.value = !isExpanded.value
}

// ── Computed helpers ──
const hasRewrites = () =>
  props.rewriteInfo.rewritten_queries && props.rewriteInfo.rewritten_queries.length > 0

const hasError = () =>
  props.rewriteInfo.error != null && props.rewriteInfo.error.length > 0

// ── Strategy display name mapping ──
const STRATEGY_LABELS: Record<string, string> = {
  context_fusion: "上下文融合",
  normalize: "规范重述",
  term_align: "术语对齐",
  expand: "扩展重述",
}
const DEFAULT_STRATEGY_LABEL = "重写"

function strategyLabel(strategy: string | null | undefined): string {
  if (strategy == null) return DEFAULT_STRATEGY_LABEL
  return STRATEGY_LABELS[strategy] ?? DEFAULT_STRATEGY_LABEL
}
</script>

<template>
  <!-- 始终显示查询重写详情面板（无触发条件） -->
  <div
    data-testid="rewrite-panel"
  >
    <!-- Collapse toggle button -->
    <button
      data-testid="rewrite-toggle"
      class="flex w-full items-center justify-between px-5 py-3 text-left transition hover:bg-neutral-50"
      type="button"
      @click="toggleExpand"
    >
      <div class="flex items-center gap-2">
        <span class="mr-1.5" aria-hidden="true">🗒️</span>
        <h3
          data-testid="rewrite-title"
          class="font-display text-sm font-semibold text-neutral-700"
        >
          查询重写详情
        </h3>
        <span
          data-testid="rewrite-count-badge"
          class="rounded-full bg-neutral-100 px-2 py-0.5 text-xs text-neutral-500"
        >
          {{ rewriteInfo.rewritten_queries.length }}
        </span>
      </div>
      <div class="flex items-center gap-2">
        <svg
          data-testid="rewrite-chevron"
          class="size-4 text-neutral-400 transition-transform"
          :class="{ 'rotate-180': isExpanded }"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </div>
    </button>

    <!-- Expanded content area -->
    <div
      v-if="isExpanded"
      data-testid="rewrite-content"
      class="border-t border-neutral-100"
    >
      <!-- Original query -->
      <div class="px-5 py-3">
        <p class="mb-1 text-[11px] font-semibold uppercase tracking-wide text-neutral-400">
          原始查询
        </p>
        <p
          data-testid="original-query"
          class="text-sm text-neutral-500 italic"
        >
          {{ rewriteInfo.original_query }}
        </p>
      </div>

      <!-- Rewritten queries list -->
      <div
        v-if="hasRewrites()"
        data-testid="rewritten-queries-list"
        class="divide-y divide-neutral-100"
      >
        <div
          v-for="(item, idx) in rewriteInfo.rewritten_queries"
          :key="idx"
          data-testid="rewritten-query-item"
          class="px-5 py-3"
        >
          <!-- Strategy tag (unified gray style for Phase 1) -->
          <div class="mb-1.5 flex items-center gap-2">
            <span
              data-testid="strategy-tag"
              class="inline-flex items-center rounded-full bg-neutral-100 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-neutral-600"
            >
              {{ strategyLabel(item.strategy) }}
            </span>
          </div>

          <!-- Query text -->
          <p
            data-testid="rewritten-query-text"
            class="text-sm leading-6 text-neutral-700"
          >
            {{ item.query }}
          </p>
        </div>
      </div>

      <!-- Empty / disabled state -->
      <div
        v-else
        data-testid="rewrite-empty-state"
        class="px-5 py-4"
      >
        <p
          data-testid="rewrite-empty-message"
          class="text-sm text-neutral-400"
        >
          {{ hasError() ? `⚠️ 重写失败：${rewriteInfo.error}` : '未启用查询重写或未产生改写结果，使用原始查询检索。' }}
        </p>
      </div>

      <!-- Performance metrics -->
      <div class="flex items-center gap-4 px-5 py-3">
        <p
          data-testid="rewrite-time"
          class="text-xs text-neutral-400"
        >
          耗时 {{ rewriteInfo.rewrite_time_ms }} ms
        </p>
        <p
          data-testid="cache-hit"
          class="text-xs"
          :class="rewriteInfo.cache_hit ? 'text-emerald-500' : 'text-neutral-400'"
        >
          {{ rewriteInfo.cache_hit ? '⚡ 缓存命中' : '缓存未命中' }}
        </p>
      </div>
    </div>
  </div>
</template>
