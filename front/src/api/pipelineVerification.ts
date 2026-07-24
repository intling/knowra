import { apiGet } from "./client"
import { createLogger, getRingBuffer } from "../shared/logger"

/** Lazy logger — getRingBuffer() is only available after main.ts initLogger(). */
let _logger: ReturnType<typeof createLogger> | null = null
function log() {
  if (!_logger) _logger = createLogger("api:pipelineVerification", getRingBuffer())
  return _logger
}

// ── Response types (matching backend Pydantic schemas) ──────────────

export interface DocumentChainInfo {
  parsed_document_id: string
  title: string | null
  original_filename: string
  content_type: string | null
  byte_size: number
}

export interface ParseJobStage {
  id: string
  status: string
}

export interface ChunkJobStage {
  id: string
  status: string
  chunker_name: string
  chunk_count: number
}

export interface EmbeddingJobStage {
  id: string
  status: string
  model: string
  dimensions: number
  embedding_count: number
}

export interface PipelineInfo {
  parse_job: ParseJobStage | null
  chunk_job: ChunkJobStage | null
  embedding_job: EmbeddingJobStage | null
}

export interface VerificationCheck {
  name: string
  passed: boolean
  message: string
}

export interface VerificationSummary {
  passed: boolean
  total_checks: number
  passed_checks: number
  checks: VerificationCheck[]
}

export interface ChunkInfo {
  id: string
  text: string | null
  contextualized_text: string | null
  text_source: string // "inline" | "file" | "unavailable"
  token_count: number | null
  heading_path: string[] | null
  page_numbers: number[] | null
}

export interface EmbeddingInfo {
  id: string
  model: string
  dimensions: number
  vector_preview: number[]
  token_count: number | null
}

export interface ChunkEmbeddingPairResponse {
  sequence_index: number
  chunk: ChunkInfo | null
  embedding: EmbeddingInfo | null
}

export interface VerificationStats {
  total_pairs: number
  total_chunk_tokens: number
  total_embedding_tokens: number
  inline_text_count: number
  file_storage_text_count: number
  embedding_dimensions: number | null
  embedding_model: string | null
}

export interface PipelineVerificationResponse {
  document: DocumentChainInfo
  pipeline: PipelineInfo
  verification: VerificationSummary
  pairs: ChunkEmbeddingPairResponse[]
  stats: VerificationStats
}

// ── Error types ────────────────────────────────────────────────────

export interface PipelineVerificationApiError {
  status: number
  detail: string
}

class PipelineVerificationError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail)
    this.name = "PipelineVerificationError"
  }
}

// ── API functions ──────────────────────────────────────────────────

/**
 * 对指定已解析文档执行流水线存取验证，返回「向量 → 分块 → 文档」全链路
 * 完整性检查结果。
 *
 * @param parsedDocumentId - 已解析文档 ID
 * @returns 结构化验证结果，包含文档信息、pipeline 阶段状态、7 项检查结果、
 *          分块-向量对照表和统计摘要
 * @throws PipelineVerificationError - 404（文档不存在/阶段缺失）或 503（用户不可用）
 */
export async function fetchPipelineVerification(
  parsedDocumentId: string,
): Promise<PipelineVerificationResponse> {
  const path = `/parsed-documents/${parsedDocumentId}/pipeline-verification`
  log().info("请求流水线验证", { parsedDocumentId })

  try {
    const result = await apiGet<PipelineVerificationResponse>(path)
    log().info("流水线验证完成", {
      parsedDocumentId,
      passed: result.verification.passed,
      passedChecks: `${result.verification.passed_checks}/${result.verification.total_checks}`,
      totalPairs: result.stats.total_pairs,
    })
    return result
  } catch (error) {
    // apiGet 对非 2xx 响应抛出通用 Error，这里转换为类型化错误
    const message = error instanceof Error ? error.message : String(error)

    // 尝试从错误消息中提取状态码
    const statusMatch = message.match(/请求失败：(\d+)/)
    const status = statusMatch ? parseInt(statusMatch[1], 10) : 0

    log().warn("流水线验证请求失败", {
      parsedDocumentId,
      status,
      message,
    })

    throw new PipelineVerificationError(
      status,
      message,
    )
  }
}
