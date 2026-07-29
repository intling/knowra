<script setup lang="ts">
import { computed, onMounted, ref } from "vue"

import { listParsedDocuments, type ParsedDocument } from "../api/documentParsing"
import {
  fetchPipelineVerification,
  type PipelineVerificationResponse,
} from "../api/pipelineVerification"
import { createLogger, getRingBuffer } from "../shared/logger"

/** Lazy logger — getRingBuffer() is only available after main.ts initLogger(). */
let _logger: ReturnType<typeof createLogger> | null = null
function log() {
  if (!_logger) _logger = createLogger("views:Verification", getRingBuffer())
  return _logger
}

// ── State ──

const parsedDocuments = ref<ParsedDocument[]>([])
const selectedDocumentId = ref<string | null>(null)
const isLoadingDocuments = ref(false)
const documentsError = ref<string | null>(null)
const isVerifying = ref(false)
const verificationResult = ref<PipelineVerificationResponse | null>(null)
const verificationError = ref<{ status: number; detail: string } | null>(null)

// ── Computed ──

const hasDocuments = computed(() => parsedDocuments.value.length > 0)
const canVerify = computed(() => selectedDocumentId.value !== null && !isVerifying.value)

const pipelineStages = computed(() => {
  if (!verificationResult.value) return []
  const p = verificationResult.value.pipeline
  return [
    { label: "解析", key: "parse", stage: p.parse_job },
    { label: "分块", key: "chunk", stage: p.chunk_job },
    { label: "向量化", key: "embedding", stage: p.embedding_job },
  ]
})

/** 截断文本用于表格展示，前缀 150 字符。 */
function truncateText(text: string | null, maxLen = 150): string {
  if (!text) return "—"
  if (text.length <= maxLen) return text
  return text.slice(0, maxLen) + "…"
}

/** 格式化向量预览为逗号分隔的浮点数。 */
function formatVectorPreview(preview: number[]): string {
  if (!preview || preview.length === 0) return "—"
  return preview.map((v) => v.toFixed(6)).join(", ") + ", …"
}

/** 获取检查项对应的状态标签样式。 */
function checkBadgeClass(passed: boolean): string {
  return passed
    ? "bg-emerald-50 text-emerald-700 border-emerald-200"
    : "bg-red-50 text-red-700 border-red-200"
}

function checkBadgeLabel(passed: boolean): string {
  return passed ? "通过" : "失败"
}

/** 检查项名称的中文映射。 */
const CHECK_NAME_LABELS: Record<string, string> = {
  chunk_embedding_pairing: "分块-向量对应关系",
  dimension_consistency: "向量维度一致性",
  sequence_continuity: "序号连续性",
  chunk_text_availability: "分块文本可读性",
  contextualized_text_availability: "上下文增强文本可读性",
  token_count_consistency: "Token 数有效性",
  model_consistency: "嵌入模型一致性",
}

function checkLabel(name: string): string {
  return CHECK_NAME_LABELS[name] ?? name
}

const stageStatusLabel: Record<string, string> = {
  succeeded: "已完成",
  queued: "排队中",
  running: "运行中",
  failed: "失败",
  cancelled: "已取消",
  superseded: "已更新",
}

function stageStatusText(status: string): string {
  return stageStatusLabel[status] ?? status
}

function stageStatusColor(status: string): string {
  switch (status) {
    case "succeeded":
      return "text-emerald-600"
    case "failed":
      return "text-red-600"
    case "queued":
    case "running":
      return "text-amber-600"
    default:
      return "text-neutral-500"
  }
}

function textSourceLabel(source: string): string {
  switch (source) {
    case "inline":
      return "内联"
    case "file":
      return "文件"
    default:
      return "不可用"
  }
}

// ── Actions ──

async function loadDocuments() {
  isLoadingDocuments.value = true
  documentsError.value = null
  log().info("开始加载已解析文档列表")

  try {
    parsedDocuments.value = await listParsedDocuments()
    log().info("已解析文档列表加载成功", { count: parsedDocuments.value.length })
  } catch (error) {
    const message = error instanceof Error ? error.message : "加载失败"
    documentsError.value = message
    log().error("已解析文档列表加载失败", error)
  } finally {
    isLoadingDocuments.value = false
  }
}

async function handleVerify() {
  if (!selectedDocumentId.value || isVerifying.value) return

  isVerifying.value = true
  verificationResult.value = null
  verificationError.value = null

  log().info("开始执行流水线验证", { parsedDocumentId: selectedDocumentId.value })

  try {
    verificationResult.value = await fetchPipelineVerification(selectedDocumentId.value)
    log().info("流水线验证完成", {
      parsedDocumentId: selectedDocumentId.value,
      passed: verificationResult.value.verification.passed,
      passedChecks: `${verificationResult.value.verification.passed_checks}/${verificationResult.value.verification.total_checks}`,
    })
  } catch (error) {
    if (
      error instanceof Error &&
      "status" in error &&
      "detail" in error
    ) {
      const apiErr = error as { status: number; detail: string }
      verificationError.value = { status: apiErr.status, detail: apiErr.detail }
    } else {
      verificationError.value = {
        status: 0,
        detail: error instanceof Error ? error.message : "验证请求失败",
      }
    }
    log().warn("流水线验证失败", {
      parsedDocumentId: selectedDocumentId.value,
      status: verificationError.value.status,
      detail: verificationError.value.detail,
    })
  } finally {
    isVerifying.value = false
  }
}

function handleDocumentChange(event: Event) {
  const select = event.target as HTMLSelectElement
  selectedDocumentId.value = select.value || null
}

// ── Lifecycle ──

onMounted(() => {
  log().info("验证页面组件挂载")
  void loadDocuments()
})
</script>

<template>
  <!-- 顶部导航栏 -->
  <nav
    data-testid="verify-navbar"
    class="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-neutral-200 bg-white px-4 shadow-sm sm:px-6"
  >
    <div class="flex items-center gap-4">
      <!-- Logo + 返回首页 -->
      <a
        data-testid="verify-nav-logo"
        class="flex items-center gap-2 text-sm font-semibold text-neutral-900 transition hover:text-brand-700"
        href="/"
      >
        <svg
          class="size-5 text-brand-700"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M12 2L2 7l10 5 10-5-10-5z" />
          <path d="M2 17l10 5 10-5" />
          <path d="M2 12l10 5 10-5" />
        </svg>
        knowra
      </a>
    </div>

    <div class="flex items-center gap-3">
      <a
        data-testid="verify-nav-back"
        class="text-sm text-neutral-500 transition hover:text-neutral-800"
        href="/"
      >
        返回首页
      </a>
      <span class="text-sm font-medium text-neutral-400">|</span>
      <span class="text-sm font-medium text-neutral-600">流程验证</span>
    </div>
  </nav>

  <section class="min-h-[calc(100vh-3.5rem)] bg-neutral-50 pb-24">
    <div class="mx-auto w-full max-w-5xl px-4 py-8 sm:py-12">
      <!-- 页面标题 -->
      <div class="mb-8">
        <h1 class="font-display mt-2 text-2xl font-semibold tracking-normal text-neutral-900 sm:text-3xl">
          向量转译分块流程验证
        </h1>
        <p class="mt-2 text-sm leading-6 text-neutral-500">
          沿「向量 → 分块 → 文档」JOIN 链路还原全链路数据，验证 7 项数据完整性检查。
        </p>
      </div>

      <!-- 文档选择器区域 -->
      <div
        data-testid="document-selector"
        class="rounded-lg border border-neutral-200 bg-white p-5 shadow-sm"
      >
        <!-- 加载中 -->
        <div
          v-if="isLoadingDocuments"
          data-testid="documents-loading"
          class="flex items-center gap-3"
        >
          <div class="h-10 w-full animate-pulse rounded-lg bg-neutral-100" />
        </div>

        <!-- 加载失败 -->
        <div
          v-else-if="documentsError"
          data-testid="documents-error"
          class="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          {{ documentsError }}
          <button
            class="ml-2 underline hover:text-red-800"
            type="button"
            @click="loadDocuments"
          >
            重试
          </button>
        </div>

        <!-- 空状态 -->
        <div
          v-else-if="!hasDocuments"
          data-testid="documents-empty"
          class="rounded-lg border border-dashed border-neutral-200 bg-neutral-50 px-4 py-8 text-center"
        >
          <p class="text-sm font-medium text-neutral-600">暂无已解析文档</p>
          <p class="mt-1 text-xs text-neutral-400">
            请先在首页上传并解析文档，完成后返回此页面进行验证。
          </p>
        </div>

        <!-- 选择器 -->
        <div v-else class="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div class="flex-1">
            <label
              for="document-select"
              class="mb-1.5 block text-sm font-medium text-neutral-600"
            >
              选择已解析文档
            </label>
            <select
              id="document-select"
              data-testid="document-select"
              class="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-neutral-900 outline-none focus:border-neutral-400 focus:ring-1 focus:ring-neutral-400"
              @change="handleDocumentChange"
            >
              <option value="">— 请选择文档 —</option>
              <option
                v-for="doc in parsedDocuments"
                :key="doc.id"
                :value="doc.id"
              >
                {{ doc.title || doc.id }} ({{ doc.segment_count }} 段)
              </option>
            </select>
          </div>
          <button
            data-testid="verify-button"
            class="h-10 rounded-md bg-brand-700 px-5 text-sm font-medium text-white transition hover:bg-brand-800 disabled:cursor-not-allowed disabled:bg-neutral-200 disabled:text-neutral-400"
            type="button"
            :disabled="!canVerify"
            @click="handleVerify"
          >
            执行验证
          </button>
        </div>
      </div>

      <!-- 验证中：骨架屏 -->
      <div
        v-if="isVerifying"
        data-testid="verification-loading"
        class="mt-6 animate-pulse space-y-4"
      >
        <div class="h-8 w-48 rounded-lg bg-neutral-200" />
        <div class="grid grid-cols-3 gap-4">
          <div class="h-20 rounded-lg bg-neutral-200" />
          <div class="h-20 rounded-lg bg-neutral-200" />
          <div class="h-20 rounded-lg bg-neutral-200" />
        </div>
        <div class="grid grid-cols-7 gap-3">
          <div
            v-for="i in 7"
            :key="i"
            class="h-16 rounded-lg bg-neutral-200"
          />
        </div>
        <div class="h-64 rounded-lg bg-neutral-200" />
      </div>

      <!-- 验证错误 -->
      <div
        v-if="verificationError && !isVerifying"
        data-testid="verification-error"
        class="mt-6 rounded-lg border border-red-200 bg-red-50 p-5"
      >
        <p class="text-sm font-medium text-red-800">
          验证失败（{{ verificationError.status }}）
        </p>
        <p class="mt-1 text-sm text-red-600">{{ verificationError.detail }}</p>
        <p
          v-if="verificationError.status === 404"
          class="mt-3 text-xs text-red-500"
        >
          <template v-if="verificationError.detail.includes('chunk job')">
            该文档尚未完成分块处理，请等待分块作业完成后再试。
          </template>
          <template v-else-if="verificationError.detail.includes('embedding job')">
            该文档已完成分块但尚未向量化，请等待向量化作业完成后再试。
          </template>
          <template v-else>
            请确认所选文档已完整经过解析、分块和向量化流程。
          </template>
        </p>
      </div>

      <!-- 验证结果 -->
      <div
        v-if="verificationResult && !isVerifying"
        data-testid="verification-result"
        class="mt-6 space-y-6"
      >
        <!-- 文档信息 -->
        <div
          data-testid="document-info"
          class="rounded-lg border border-neutral-200 bg-white p-5 shadow-sm"
        >
          <h2 class="font-display text-sm font-semibold text-neutral-700">文档信息</h2>
          <dl class="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
            <div>
              <dt class="text-xs text-neutral-400">标题</dt>
              <dd class="text-sm text-neutral-900">
                {{ verificationResult.document.title || "未命名" }}
              </dd>
            </div>
            <div>
              <dt class="text-xs text-neutral-400">原始文件名</dt>
              <dd class="text-sm text-neutral-900">
                {{ verificationResult.document.original_filename }}
              </dd>
            </div>
            <div>
              <dt class="text-xs text-neutral-400">内容类型</dt>
              <dd class="text-sm text-neutral-900">
                {{ verificationResult.document.content_type || "—" }}
              </dd>
            </div>
            <div>
              <dt class="text-xs text-neutral-400">文件大小</dt>
              <dd class="text-sm text-neutral-900">
                {{ (verificationResult.document.byte_size / 1024).toFixed(1) }} KB
              </dd>
            </div>
            <div>
              <dt class="text-xs text-neutral-400">文档 ID</dt>
              <dd class="text-sm font-mono text-neutral-500 text-xs">
                {{ verificationResult.document.parsed_document_id }}
              </dd>
            </div>
          </dl>
        </div>

        <!-- Pipeline 链路展示 -->
        <div
          data-testid="pipeline-stages"
          class="rounded-lg border border-neutral-200 bg-white p-5 shadow-sm"
        >
          <h2 class="font-display text-sm font-semibold text-neutral-700">Pipeline 链路</h2>
          <div class="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div
              v-for="(item, idx) in pipelineStages"
              :key="item.key"
              class="flex items-center gap-3 rounded-lg border border-neutral-100 bg-neutral-50 px-4 py-3"
            >
              <span
                class="flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-bold"
                :class="
                  item.stage
                    ? item.stage.status === 'succeeded'
                      ? 'bg-emerald-100 text-emerald-700'
                      : item.stage.status === 'failed'
                        ? 'bg-red-100 text-red-700'
                        : 'bg-amber-100 text-amber-700'
                    : 'bg-neutral-200 text-neutral-400'
                "
              >
                {{ idx + 1 }}
              </span>
              <div class="min-w-0">
                <p class="text-sm font-medium text-neutral-800">{{ item.label }}</p>
                <p
                  v-if="item.stage"
                  class="text-xs"
                  :class="stageStatusColor(item.stage.status)"
                >
                  {{ stageStatusText(item.stage.status) }}
                </p>
                <p v-else class="text-xs text-neutral-400">不可用</p>
              </div>
            </div>
          </div>
          <!-- 分块/向量化详情 -->
          <div
            v-if="verificationResult.pipeline.chunk_job || verificationResult.pipeline.embedding_job"
            class="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-neutral-500"
          >
            <template v-if="verificationResult.pipeline.chunk_job">
              <span>分块器：{{ verificationResult.pipeline.chunk_job.chunker_name }}</span>
              <span>分块数：{{ verificationResult.pipeline.chunk_job.chunk_count }}</span>
            </template>
            <template v-if="verificationResult.pipeline.embedding_job">
              <span>模型：{{ verificationResult.pipeline.embedding_job.model }}</span>
              <span
                >维度：{{ verificationResult.pipeline.embedding_job.dimensions }} ·
                数量：{{ verificationResult.pipeline.embedding_job.embedding_count }}</span
              >
            </template>
          </div>
        </div>

        <!-- 验证摘要面板 -->
        <div
          data-testid="verification-summary"
          class="rounded-lg border border-neutral-200 bg-white p-5 shadow-sm"
        >
          <div class="flex flex-wrap items-center justify-between gap-3">
            <h2 class="font-display text-sm font-semibold text-neutral-700">完整性检查结果</h2>
            <span
              class="inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium"
              :class="
                verificationResult.verification.passed
                  ? 'bg-emerald-50 text-emerald-700'
                  : 'bg-red-50 text-red-700'
              "
            >
              {{ verificationResult.verification.passed_checks }}/{{
                verificationResult.verification.total_checks
              }}
              通过
            </span>
          </div>
          <div class="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div
              v-for="check in verificationResult.verification.checks"
              :key="check.name"
              data-testid="check-item"
              class="rounded-lg border px-3 py-2.5"
              :class="checkBadgeClass(check.passed)"
            >
              <div class="flex items-center justify-between gap-1">
                <p class="text-xs font-medium">{{ checkLabel(check.name) }}</p>
                <span
                  class="shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-semibold"
                  :class="
                    check.passed
                      ? 'bg-emerald-100 text-emerald-700'
                      : 'bg-red-100 text-red-700'
                  "
                >
                  {{ checkBadgeLabel(check.passed) }}
                </span>
              </div>
              <p class="mt-1 text-xs opacity-80">{{ check.message }}</p>
            </div>
          </div>
        </div>

        <!-- 统计卡片 -->
        <div
          data-testid="verification-stats"
          class="grid grid-cols-2 gap-3 sm:grid-cols-4"
        >
          <div class="rounded-lg border border-neutral-200 bg-white px-4 py-3 shadow-sm">
            <p class="text-xs text-neutral-400">总配对数</p>
            <p class="mt-1 text-xl font-semibold text-neutral-900">
              {{ verificationResult.stats.total_pairs }}
            </p>
          </div>
          <div class="rounded-lg border border-neutral-200 bg-white px-4 py-3 shadow-sm">
            <p class="text-xs text-neutral-400">Chunk Token 总数</p>
            <p class="mt-1 text-xl font-semibold text-neutral-900">
              {{ verificationResult.stats.total_chunk_tokens }}
            </p>
          </div>
          <div class="rounded-lg border border-neutral-200 bg-white px-4 py-3 shadow-sm">
            <p class="text-xs text-neutral-400">文本来源</p>
            <p class="mt-1 text-sm font-medium text-neutral-900">
              内联 {{ verificationResult.stats.inline_text_count }} · 文件
              {{ verificationResult.stats.file_storage_text_count }}
            </p>
          </div>
          <div class="rounded-lg border border-neutral-200 bg-white px-4 py-3 shadow-sm">
            <p class="text-xs text-neutral-400">嵌入模型</p>
            <p class="mt-1 text-sm font-medium text-neutral-900">
              {{ verificationResult.stats.embedding_model || "—" }}
              <span
                v-if="verificationResult.stats.embedding_dimensions"
                class="text-xs text-neutral-400"
              >
                · {{ verificationResult.stats.embedding_dimensions }} 维
              </span>
            </p>
          </div>
        </div>

        <!-- 分块-向量对照表 -->
        <div
          data-testid="pairs-table"
          class="rounded-lg border border-neutral-200 bg-white shadow-sm"
        >
          <div class="border-b border-neutral-100 px-5 py-3">
            <h2 class="font-display text-sm font-semibold text-neutral-700">
              分块-向量对照表（{{ verificationResult.pairs.length }} 条）
            </h2>
          </div>
          <div class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead>
                <tr class="border-b border-neutral-100 bg-neutral-50 text-neutral-500">
                  <th class="px-4 py-2.5 font-medium">序号</th>
                  <th class="px-4 py-2.5 font-medium">Chunk 文本</th>
                  <th class="px-4 py-2.5 font-medium">上下文增强文本</th>
                  <th class="px-4 py-2.5 font-medium">Token 数</th>
                  <th class="px-4 py-2.5 font-medium">向量前 5 维</th>
                  <th class="px-4 py-2.5 font-medium">来源</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="pair in verificationResult.pairs"
                  :key="pair.sequence_index"
                  data-testid="pair-row"
                  class="border-b border-neutral-50 hover:bg-neutral-50/50"
                >
                  <td class="px-4 py-2.5 font-mono text-neutral-600">
                    #{{ pair.sequence_index }}
                  </td>
                  <td class="max-w-64 px-4 py-2.5 text-neutral-800">
                    <span
                      v-if="pair.chunk?.text"
                      class="line-clamp-2"
                      :title="pair.chunk.text"
                    >
                      {{ truncateText(pair.chunk.text) }}
                    </span>
                    <span v-else class="italic text-neutral-400">孤儿 embedding</span>
                  </td>
                  <td class="max-w-48 px-4 py-2.5 text-neutral-600">
                    <span v-if="pair.chunk?.contextualized_text" class="line-clamp-2">
                      {{ truncateText(pair.chunk.contextualized_text, 100) }}
                    </span>
                    <span v-else class="text-neutral-400">—</span>
                  </td>
                  <td class="px-4 py-2.5 font-mono text-neutral-600">
                    {{ pair.chunk?.token_count ?? "—" }}
                  </td>
                  <td class="max-w-48 px-4 py-2.5 font-mono text-neutral-500">
                    <span v-if="pair.embedding?.vector_preview?.length">
                      {{ formatVectorPreview(pair.embedding.vector_preview) }}
                    </span>
                    <span v-else class="italic text-neutral-400">孤儿 chunk</span>
                  </td>
                  <td class="px-4 py-2.5">
                    <span
                      class="inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium"
                      :class="
                        pair.chunk?.text_source === 'inline'
                          ? 'bg-brand-50 text-blue-600'
                          : pair.chunk?.text_source === 'file'
                            ? 'bg-amber-50 text-amber-600'
                            : 'bg-red-50 text-red-600'
                      "
                    >
                      {{ textSourceLabel(pair.chunk?.text_source ?? "unavailable") }}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
