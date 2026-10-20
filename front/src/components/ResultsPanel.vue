<script setup lang="ts">
import { computed, ref } from "vue"

import type { SearchResultItem } from "../api/search"
import PanelSection from "./shared/PanelSection.vue"

const props = withDefaults(
  defineProps<{
    results?: SearchResultItem[]
    searchedDocumentCount?: number
    totalSearched?: number
    searchTimeMs?: number
    variant?: "card" | "flat"
  }>(),
  {
    results: () => [],
    searchedDocumentCount: 0,
    totalSearched: 0,
    searchTimeMs: 0,
    variant: "card",
  },
)

// ── Format helper ──
function formatMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`
  return `${(ms / 1000).toFixed(1)} s`
}

// ── Expand/collapse individual result text ──
const expandedTextIndices = ref<Set<number>>(new Set())

function toggleTextExpand(index: number) {
  const next = new Set(expandedTextIndices.value)
  if (next.has(index)) {
    next.delete(index)
  } else {
    next.add(index)
  }
  expandedTextIndices.value = next
}

function isTextExpanded(index: number): boolean {
  return expandedTextIndices.value.has(index)
}

// ── Results grouped by document ──
interface DocGroup {
  documentName: string
  results: { item: SearchResultItem; globalIndex: number }[]
}

const docGroups = computed<DocGroup[]>(() => {
  const map = new Map<
    string,
    { item: SearchResultItem; globalIndex: number }[]
  >()
  props.results.forEach((item, idx) => {
    const name = item.document_name || "未知文档"
    if (!map.has(name)) map.set(name, [])
    map.get(name)!.push({ item, globalIndex: idx })
  })
  return Array.from(map.entries()).map(([documentName, results]) => ({
    documentName,
    results,
  }))
})

// ── 相似度分数条：similarity = clamp(1 − 余弦距离, 0, 1) ──
function similarity(score: number): number {
  return Math.min(1, Math.max(0, 1 - score))
}

function scoreBarWidth(score: number): string {
  return `${Math.round(similarity(score) * 100)}%`
}

function scoreBarColor(score: number): string {
  const sim = similarity(score)
  if (sim >= 0.75) return "bg-brand-600"
  if (sim >= 0.5) return "bg-amber-500"
  return "bg-neutral-400"
}

// ── Score distribution bins (task 6.7) ──
const scoreBins = computed(() => {
  if (props.results.length === 0) return []
  const scores = props.results.map((r) => r.score)
  const min = Math.min(...scores)
  const max = Math.max(...scores)
  const range = max - min || 0.001
  const binCount = Math.min(8, props.results.length)
  const binWidth = range / binCount

  const bins: { label: string; count: number; heightPct: number }[] = []
  const maxCount = props.results.length

  for (let i = 0; i < binCount; i++) {
    const binMin = min + i * binWidth
    const binMax = binMin + binWidth
    const count = scores.filter(
      (s) => s >= binMin && (i === binCount - 1 ? s <= binMax : s < binMax),
    ).length
    bins.push({
      label: binMin.toFixed(3),
      count,
      heightPct: maxCount > 0 ? (count / maxCount) * 100 : 0,
    })
  }
  return bins
})
</script>

<template>
  <PanelSection
    title="检索结果"
    collapsible
    :default-expanded="false"
    testid="results"
    :variant="variant"
  >
    <template #icon>
      <svg
        class="size-3.5"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <circle cx="11" cy="11" r="8" />
        <path d="m21 21-4.3-4.3" />
      </svg>
    </template>
    <template #badge>
      <span
        v-if="results.length > 0"
        class="rounded-full bg-neutral-100 px-2 py-0.5 text-xs text-neutral-500"
      >
        {{ results.length }} 条
      </span>
    </template>

    <div data-testid="results-content">
      <!-- Search summary bar -->
      <div
        class="flex flex-wrap items-center gap-x-5 gap-y-1 px-4 py-3 text-xs text-neutral-500"
      >
        <span
          data-testid="search-summary"
          class="inline-flex items-center gap-1"
        >
          <svg
            class="size-3.5"
            aria-hidden="true"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <circle cx="11" cy="11" r="8" />
            <path
              d="m21 21-4.3-4.3"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
          搜索 {{ searchedDocumentCount }} 个文档 · {{ totalSearched }} 个向量 ·
          耗时
          {{ formatMs(searchTimeMs) }}
        </span>
      </div>

      <!-- Score distribution mini bar chart (task 6.7) -->
      <div
        v-if="scoreBins.length > 0"
        data-testid="score-distribution"
        class="border-t border-neutral-100 px-4 py-3"
      >
        <p class="mb-2 text-xs font-medium text-neutral-500">
          分数分布（余弦距离，越小越相似）
        </p>
        <div class="flex items-end gap-1" style="height: 48px">
          <div
            v-for="(bin, i) in scoreBins"
            :key="i"
            class="group relative flex flex-1 flex-col items-center justify-end"
            :title="`${bin.label} – ${bin.count} 条`"
          >
            <div
              class="w-full rounded-t-sm bg-neutral-400 transition-colors group-hover:bg-neutral-600"
              :style="{ height: Math.max(4, bin.heightPct * 0.48) + 'px' }"
            />
            <span
              v-if="scoreBins.length <= 6"
              class="mt-1 text-[10px] leading-none text-neutral-400"
            >
              {{ bin.label }}
            </span>
          </div>
        </div>
        <div class="mt-2 flex justify-between text-[10px] text-neutral-400">
          <span>更相似 →</span>
          <span>← 更不相似</span>
        </div>
      </div>

      <!-- Empty results -->
      <div
        v-if="results.length === 0"
        data-testid="results-empty"
        class="border-t border-neutral-100 px-4 py-10 text-center"
      >
        <p class="text-sm text-neutral-400">未找到相关结果</p>
      </div>

      <!-- Results list grouped by document -->
      <div v-else class="border-t border-neutral-100">
        <div
          v-for="group in docGroups"
          :key="group.documentName"
          class="[&+&]:border-t border-neutral-100"
        >
          <!-- Document group header -->
          <div class="flex items-center gap-2 bg-neutral-50 px-4 py-2">
            <svg
              class="size-3.5 text-neutral-400"
              aria-hidden="true"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
            >
              <path
                d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
              <polyline
                points="14 2 14 8 20 8"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
            <span class="text-xs font-medium text-neutral-600">
              {{ group.documentName }}
            </span>
            <span
              class="rounded-full bg-neutral-200 px-1.5 py-0.5 text-[10px] text-neutral-500"
            >
              {{ group.results.length }} 条
            </span>
          </div>

          <!-- Results in group -->
          <ul>
            <li
              v-for="{ item, globalIndex } in group.results"
              :key="item.chunk_id"
              data-testid="result-item"
              class="border-t border-neutral-50 px-4 py-3"
            >
              <!-- Rank + score bar -->
              <div class="flex items-center gap-3">
                <span
                  class="flex size-5 shrink-0 items-center justify-center rounded-full bg-neutral-100 text-[10px] font-semibold text-neutral-500"
                >
                  {{ item.rank }}
                </span>
                <div class="flex min-w-0 flex-1 items-center gap-2">
                  <div
                    class="h-2 flex-1 overflow-hidden rounded-full bg-neutral-100"
                  >
                    <div
                      data-testid="result-score-bar"
                      :class="scoreBarColor(item.score)"
                      class="h-full rounded-full transition-all"
                      :style="{ width: scoreBarWidth(item.score) }"
                    />
                  </div>
                  <span
                    class="shrink-0 text-xs tabular-nums text-neutral-500"
                    :title="`余弦距离 ${item.score.toFixed(4)}`"
                  >
                    相似度 {{ similarity(item.score).toFixed(2) }}
                  </span>
                </div>
              </div>

              <!-- Chunk text (truncated + expand) -->
              <div class="mt-2">
                <p
                  class="text-sm leading-6 text-neutral-700"
                  :class="{ 'line-clamp-3': !isTextExpanded(globalIndex) }"
                >
                  {{ item.text || "（无文本内容）" }}
                </p>
                <button
                  v-if="item.text && item.text.length > 150"
                  class="mt-1 text-xs text-neutral-400 transition hover:text-neutral-600"
                  type="button"
                  @click="toggleTextExpand(globalIndex)"
                >
                  {{ isTextExpanded(globalIndex) ? "收起" : "展开全文" }}
                </button>
              </div>

              <!-- Metadata row -->
              <div
                class="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-neutral-400"
              >
                <span
                  v-if="item.page_numbers && item.page_numbers.length > 0"
                  class="inline-flex items-center gap-1"
                >
                  <svg
                    class="size-3"
                    aria-hidden="true"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                  >
                    <path
                      d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"
                      stroke-linecap="round"
                    />
                    <path
                      d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"
                      stroke-linecap="round"
                    />
                  </svg>
                  第 {{ item.page_numbers.join(", ") }} 页
                </span>
                <span
                  v-if="item.heading_path && item.heading_path.length > 0"
                  class="inline-flex items-center gap-1"
                >
                  <svg
                    class="size-3"
                    aria-hidden="true"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                  >
                    <path d="M3 12h18M3 6h18M3 18h18" stroke-linecap="round" />
                  </svg>
                  {{ item.heading_path.join(" › ") }}
                </span>
                <span
                  v-if="
                    item.token_count !== null && item.token_count !== undefined
                  "
                  class="inline-flex items-center gap-1"
                >
                  <svg
                    class="size-3"
                    aria-hidden="true"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                  >
                    <rect x="2" y="4" width="20" height="16" rx="2" />
                    <path d="M6 8h.01M10 8h.01" stroke-linecap="round" />
                  </svg>
                  {{ item.token_count }} tokens
                </span>
                <span class="inline-flex items-center gap-1">
                  分块 #{{ item.sequence_index }}
                </span>
              </div>
            </li>
          </ul>
        </div>
      </div>
    </div>
  </PanelSection>
</template>
