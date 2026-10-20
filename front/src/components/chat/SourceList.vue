<script setup lang="ts">
/**
 * SourceList — 回答正下方的来源列表。
 *
 * 按 parsed_document_id 聚合本轮检索结果（同名不同 ID 的文档分开），
 * 默认显示首个片段预览；展开后原样展示每个片段的 API 原文、原始排名与分块编号。
 */
import { computed, ref } from "vue"

import type { SearchResultItem } from "../../api/search"
import { uniqueId } from "../../shared/a11y/focus"

const props = defineProps<{
  results: SearchResultItem[]
}>()

interface SourceGroup {
  key: string
  name: string
  chunks: SearchResultItem[]
  pages: number[]
}

const groups = computed<SourceGroup[]>(() => {
  const map = new Map<string, SourceGroup>()
  for (const item of props.results) {
    const key = item.parsed_document_id
    let group = map.get(key)
    if (!group) {
      group = { key, name: item.document_name || "未命名文档", chunks: [], pages: [] }
      map.set(key, group)
    }
    group.chunks.push(item)
  }
  for (const group of map.values()) {
    const pages = new Set<number>()
    group.chunks.forEach((c) => c.page_numbers?.forEach((p) => pages.add(p)))
    group.pages = [...pages].sort((a, b) => a - b)
  }
  return [...map.values()]
})

const idPrefix = uniqueId("sources")
const expanded = ref<Set<string>>(new Set())

function toggle(key: string) {
  const next = new Set(expanded.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expanded.value = next
}
</script>

<template>
  <section data-testid="source-list" class="min-w-0" :aria-labelledby="`${idPrefix}-title`">
    <h3
      :id="`${idPrefix}-title`"
      data-testid="source-list-title"
      class="mb-2 flex items-center gap-2 font-sans text-xs font-semibold tracking-[0.08em] text-ink-faint"
    >
      <span>来源</span>
      <span v-if="groups.length > 0" class="font-normal">· {{ groups.length }} 份文档</span>
    </h3>

    <p
      v-if="groups.length === 0"
      data-testid="sources-empty"
      class="rounded-[var(--radius-button)] border border-cite/30 bg-cite-soft/60 px-3 py-2 text-sm text-cite"
    >
      没有检索到相关资料，本回答缺少资料依据。
    </p>

    <ol v-else class="divide-y divide-line overflow-hidden rounded-[var(--radius-card)] border border-line bg-surface">
      <li v-for="(group, index) in groups" :key="group.key" data-testid="source-item" class="min-w-0">
        <button
          type="button"
          data-testid="source-toggle"
          class="flex w-full min-w-0 items-start gap-3 px-3.5 py-3 text-left transition-colors hover:bg-paper"
          :aria-expanded="expanded.has(group.key)"
          :aria-controls="`${idPrefix}-${index}`"
          @click="toggle(group.key)"
        >
          <span
            data-testid="source-index"
            class="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border border-cite/50 font-display text-[11px] font-semibold text-cite tabular-nums"
            >{{ index + 1 }}</span
          >
          <span class="min-w-0 flex-1">
            <span class="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span data-testid="source-doc-name" class="text-[13.5px] font-medium text-ink [overflow-wrap:anywhere]">{{
                group.name
              }}</span>
              <span v-if="group.pages.length > 0" data-testid="source-pages" class="text-xs text-ink-faint tabular-nums"
                >第 {{ group.pages.join("、") }} 页</span
              >
            </span>
            <span class="mt-0.5 block text-xs text-ink-faint tabular-nums">
              <span v-for="(chunk, i) in group.chunks" :key="chunk.chunk_id"
                >{{ i > 0 ? " · " : "" }}分块 #{{ chunk.sequence_index }}</span
              >
            </span>
            <span
              v-if="!expanded.has(group.key)"
              data-testid="source-preview"
              class="mt-1.5 line-clamp-2 block text-[13px] leading-relaxed text-ink-muted [overflow-wrap:anywhere]"
              >{{ group.chunks[0]?.text || "（该片段没有文本内容）" }}</span
            >
          </span>
          <svg
            class="mt-1 size-4 shrink-0 text-ink-faint transition-transform"
            :class="{ 'rotate-180': expanded.has(group.key) }"
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

        <div
          v-if="expanded.has(group.key)"
          :id="`${idPrefix}-${index}`"
          class="space-y-2.5 border-t border-line/70 bg-paper/60 px-3.5 py-3 pl-11"
        >
          <article v-for="chunk in group.chunks" :key="chunk.chunk_id" data-testid="source-chunk" class="min-w-0">
            <p class="mb-1 flex flex-wrap gap-x-3 text-[11px] text-ink-faint tabular-nums">
              <span>检索排名 #{{ chunk.rank }}</span>
              <span>分块 #{{ chunk.sequence_index }}</span>
              <span v-if="chunk.page_numbers && chunk.page_numbers.length > 0">第 {{ chunk.page_numbers.join("、") }} 页</span>
              <span v-if="chunk.heading_path && chunk.heading_path.length > 0" class="[overflow-wrap:anywhere]">{{
                chunk.heading_path.join(" › ")
              }}</span>
            </p>
            <p
              data-testid="source-chunk-text"
              class="border-l-2 border-cite/40 pl-3 text-[13px] leading-relaxed whitespace-pre-wrap text-ink [overflow-wrap:anywhere]"
            >{{ chunk.text }}</p>
          </article>
        </div>
      </li>
    </ol>
  </section>
</template>
