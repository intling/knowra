import { apiGet, buildApiUrl } from "./client"
import { createLogger, getRingBuffer } from "../shared/logger"

/** Lazy logger — getRingBuffer() is only available after main.ts initLogger(). */
let _logger: ReturnType<typeof createLogger> | null = null
function log() {
  if (!_logger) _logger = createLogger("api:embedding", getRingBuffer())
  return _logger
}

export type DocumentEmbeddingJobStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "superseded"

export interface DocumentEmbeddingJob {
  id: string
  chunk_job_id: string
  parsed_document_id: string
  owner_user_id: string
  status: DocumentEmbeddingJobStatus
  embedder_name: string
  model: string
  dimensions: number
  embedding_count: number
  attempt_count: number
  started_at: string | null
  finished_at: string | null
  error_code: string | null
  error_message: string | null
  config_json: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface DocumentEmbedding {
  id: string
  chunk_id: string
  embedding_job_id: string
  sequence_index: number
  model: string
  dimensions: number
  embedding_json: number[]
  token_count: number | null
  created_at: string
}

export interface EmbeddingPageResponse {
  items: DocumentEmbedding[]
  total: number
  offset: number
  limit: number
}

export interface ReEmbedRequest {
  model?: string
  dimensions?: number
}

export interface EmbeddingConflictError {
  status: 409
  detail: string
  job: DocumentEmbeddingJob
}

class EmbeddingApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
    public extra?: Record<string, unknown>,
  ) {
    super(detail)
    this.name = "EmbeddingApiError"
  }
}

async function parseErrorResponse(response: Response): Promise<EmbeddingApiError> {
  try {
    const payload = (await response.json()) as Record<string, unknown>
    const detail =
      typeof payload.detail === "string"
        ? payload.detail
        : `请求失败：${response.status}`
    const extra = Object.fromEntries(
      Object.entries(payload).filter(([key]) => key !== "detail"),
    )

    return new EmbeddingApiError(
      response.status,
      detail,
      Object.keys(extra).length > 0 ? extra : undefined,
    )
  } catch {
    return new EmbeddingApiError(response.status, `请求失败：${response.status}`)
  }
}

/** 查询单个向量化作业状态。 */
export function getDocumentEmbeddingJob(jobId: string): Promise<DocumentEmbeddingJob> {
  return apiGet<DocumentEmbeddingJob>(`/document-embedding-jobs/${jobId}`)
}

/** 查询分块作业最新的向量化作业（不限状态），用于前端展示向量化进度。 */
export function getChunkJobLatestEmbeddingJob(chunkJobId: string): Promise<DocumentEmbeddingJob> {
  return apiGet<DocumentEmbeddingJob>(`/document-chunk-jobs/${chunkJobId}/embedding-job`)
}

/** 分页查询分块作业的最新活跃向量结果，按 sequence_index 排序。 */
export function getChunkJobEmbeddings(
  chunkJobId: string,
  { offset = 0, limit = 50 }: { offset?: number; limit?: number } = {},
): Promise<EmbeddingPageResponse> {
  return apiGet<EmbeddingPageResponse>(
    `/document-chunk-jobs/${chunkJobId}/embeddings?offset=${offset}&limit=${limit}`,
  )
}

/** 查询单个 chunk 的向量详情。 */
export function getChunkEmbedding(chunkId: string): Promise<DocumentEmbedding> {
  return apiGet<DocumentEmbedding>(`/document-chunks/${chunkId}/embedding`)
}

/** 触发重新向量化，返回 202 和新创建的作业。 */
export async function reembedChunkJob(
  chunkJobId: string,
  request: ReEmbedRequest = {},
): Promise<DocumentEmbeddingJob> {
  const response = await fetch(
    buildApiUrl(`/document-chunk-jobs/${chunkJobId}/re-embed`),
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    },
  )

  if (response.status === 409) {
    const payload = (await response.json()) as {
      detail: string
      job: DocumentEmbeddingJob
    }
    throw {
      status: 409,
      detail: payload.detail,
      job: payload.job,
    } as EmbeddingConflictError
  }

  if (response.status === 503) {
    throw new EmbeddingApiError(503, "服务正在关闭，请稍后重试")
  }

  if (!response.ok) {
    throw await parseErrorResponse(response)
  }

  log().info("Re-embed job created", { chunkJobId })
  return response.json() as Promise<DocumentEmbeddingJob>
}
