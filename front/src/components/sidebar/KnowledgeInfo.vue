<script setup lang="ts">
/**
 * KnowledgeInfo — 侧边栏「资料库」分区。
 *
 * 只读调用 GET /api/parsed-documents，展示已解析资料数量。
 * 解析完成不代表已建索引，因此文案只说「已解析」，不宣称「可检索」。
 */
import { onMounted, ref } from "vue"

import { listParsedDocuments } from "../../api/documentParsing"
import { createLogger, getRingBuffer } from "../../shared/logger"

let _logger: ReturnType<typeof createLogger> | null = null
function log() {
  if (!_logger) _logger = createLogger("components:KnowledgeInfo", getRingBuffer())
  return _logger
}

const count = ref(0)
const isLoading = ref(true)
const error = ref<string | null>(null)

async function load() {
  isLoading.value = true
  error.value = null
  try {
    const documents = await listParsedDocuments()
    count.value = documents.length
    log().info("已解析资料数量加载完成", { count: count.value })
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
    log().warn("已解析资料数量加载失败", { error: error.value })
  } finally {
    isLoading.value = false
  }
}

onMounted(load)
</script>

<template>
  <section data-testid="knowledge-info" class="px-3">
    <h2 class="px-1 pb-1.5 text-[11px] font-semibold tracking-[0.1em] text-ink-faint">资料库</h2>

    <div v-if="isLoading" data-testid="knowledge-loading" class="space-y-1.5 px-1 py-1.5">
      <div class="h-3 w-24 animate-pulse rounded bg-neutral-200" />
      <div class="h-2.5 w-16 animate-pulse rounded bg-neutral-100" />
    </div>

    <p v-else-if="error" data-testid="knowledge-error" class="px-1 py-1 text-xs text-ink-muted">
      资料库状态获取失败
      <button
        type="button"
        data-testid="knowledge-retry"
        class="-mx-1 ml-1 rounded px-1 py-0.5 text-brand-700 underline underline-offset-2 hover:text-brand-800"
        @click="load"
      >
        重试
      </button>
    </p>

    <p v-else-if="count === 0" data-testid="knowledge-empty" class="px-1 py-1 text-xs leading-relaxed text-ink-muted">
      还没有已解析的资料。在对话框中上传后即可提问。
    </p>

    <p v-else data-testid="knowledge-count" class="px-1 py-1 text-xs leading-relaxed text-ink-muted">
      <span class="font-semibold text-ink tabular-nums">{{ count }}</span> 份已解析资料
    </p>

    <a
      data-testid="knowledge-verify-link"
      href="/verify"
      class="mt-1 flex items-center justify-between gap-2 rounded-[var(--radius-button)] px-1 py-1.5 text-xs text-ink-muted transition-colors hover:bg-paper/70 hover:text-brand-800"
    >
      <span>流程验证</span>
      <svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M5 12h14M13 6l6 6-6 6" />
      </svg>
    </a>
  </section>
</template>
