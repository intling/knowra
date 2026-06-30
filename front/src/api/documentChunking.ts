import { apiGet, buildApiUrl } from "./client"

export type DocumentChunkJobStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "superseded"

export interface DocumentChunkJob {
  id: string
  parsed_document_id: string
  owner_user_id: string
  status: DocumentChunkJobStatus
  chunker_name: string
  chunker_version: string | null
  chunk_config_json: Record<string, unknown> | null
  chunk_count: number
  attempt_count: number
  started_at: string | null
  finished_at: string | null
  error_code: string | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface DocumentChunk {
  id: string
  chunk_job_id: string
  parsed_document_id: string
  owner_user_id: string
  sequence_index: number
  text: string | null
  contextualized_text: string | null
  token_count: number | null
  heading_path: string[] | null
  page_numbers: number[] | null
  chunk_type: string | null
  source_segment_indices: number[] | null
  metadata: Record<string, unknown> | null
  created_at: string
}

export interface DocumentChunkPage {
  items: DocumentChunk[]
  total: number
  offset: number
  limit: number
}

export interface RechunkRequest {
  max_tokens?: number
  tokenizer_model?: string
  merge_peers?: boolean
  repeat_table_header?: boolean
}

export interface DocumentChunkConflictError {
  status: 409
  detail: string
  job: DocumentChunkJob
}

class DocumentChunkingApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
    public extra?: Record<string, unknown>,
  ) {
    super(detail)
    this.name = "DocumentChunkingApiError"
  }
}

async function parseErrorResponse(response: Response): Promise<DocumentChunkingApiError> {
  try {
    const payload = (await response.json()) as Record<string, unknown>
    const detail =
      typeof payload.detail === "string"
        ? payload.detail
        : `请求失败：${response.status}`
    const extra = Object.fromEntries(
      Object.entries(payload).filter(([key]) => key !== "detail"),
    )

    return new DocumentChunkingApiError(
      response.status,
      detail,
      Object.keys(extra).length > 0 ? extra : undefined,
    )
  } catch {
    return new DocumentChunkingApiError(response.status, `请求失败：${response.status}`)
  }
}

export function getDocumentChunkJob(jobId: string): Promise<DocumentChunkJob> {
  return apiGet<DocumentChunkJob>(`/document-chunk-jobs/${jobId}`)
}

export function getLatestParsedDocumentChunkJob(
  parsedDocumentId: string,
): Promise<DocumentChunkJob> {
  return apiGet<DocumentChunkJob>(
    `/parsed-documents/${parsedDocumentId}/chunk-job`,
  )
}

export function getParsedDocumentChunks(
  parsedDocumentId: string,
  { offset = 0, limit = 20 }: { offset?: number; limit?: number } = {},
): Promise<DocumentChunkPage> {
  return apiGet<DocumentChunkPage>(
    `/parsed-documents/${parsedDocumentId}/chunks?offset=${offset}&limit=${limit}`,
  )
}

export function getDocumentChunk(chunkId: string): Promise<DocumentChunk> {
  return apiGet<DocumentChunk>(`/document-chunks/${chunkId}`)
}

export async function rechunkParsedDocument(
  parsedDocumentId: string,
  request: RechunkRequest = {},
): Promise<DocumentChunkJob> {
  const response = await fetch(
    buildApiUrl(`/parsed-documents/${parsedDocumentId}/rechunk`),
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
      job: DocumentChunkJob
    }
    throw {
      status: 409,
      detail: payload.detail,
      job: payload.job,
    } as DocumentChunkConflictError
  }

  if (!response.ok) {
    throw await parseErrorResponse(response)
  }

  return response.json() as Promise<DocumentChunkJob>
}
