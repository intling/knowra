import { apiGet } from "./client"

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api"

function buildApiUrl(path: string): string {
  const baseUrl = API_BASE_URL.replace(/\/$/, "")
  const normalizedPath = path.startsWith("/") ? path : `/${path}`
  return `${baseUrl}${normalizedPath}`
}

export interface DocumentParseJob {
  id: string
  uploaded_file_id: string
  owner_user_id: string
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled"
  parser_name: string
  parser_version: string | null
  attempt_count: number
  started_at: string | null
  finished_at: string | null
  error_code: string | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface ParsedDocument {
  id: string
  uploaded_file_id: string
  parse_job_id: string
  owner_user_id: string
  source_checksum_sha256: string | null
  markdown_storage_key: string
  text_storage_key: string
  docling_json_storage_key: string
  title: string | null
  page_count: number | null
  metadata: Record<string, unknown> | null
  segment_count: number
  created_at: string
}

export interface DocumentSegment {
  id: string
  parsed_document_id: string
  owner_user_id: string
  sequence_index: number
  segment_type: string
  page_no: number | null
  heading_path: string[] | null
  text: string
  metadata: Record<string, unknown> | null
  created_at: string
}

export interface DocumentSegmentPage {
  items: DocumentSegment[]
  total: number
  offset: number
  limit: number
}

export interface DocumentParseConflictError {
  status: 409
  detail: string
  job: DocumentParseJob
  uploadedFile: {
    id: string
    original_filename: string
    content_type: string | null
    byte_size: number
    status: string
  }
}

class DocumentParseApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
    public extra?: Record<string, unknown>,
  ) {
    super(detail)
    this.name = "DocumentParseApiError"
  }
}

async function parseErrorResponse(response: Response): Promise<DocumentParseApiError> {
  try {
    const payload = (await response.json()) as Record<string, unknown>
    const detail = typeof payload.detail === "string" ? payload.detail : `请求失败：${response.status}`
    const extra: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(payload)) {
      if (key !== "detail") {
        extra[key] = value
      }
    }
    return new DocumentParseApiError(response.status, detail, Object.keys(extra).length > 0 ? extra : undefined)
  } catch {
    return new DocumentParseApiError(response.status, `请求失败：${response.status}`)
  }
}

export async function createDocumentParseJob(uploadId: string): Promise<DocumentParseJob> {
  const url = buildApiUrl(`/uploads/${uploadId}/parse`)
  const response = await fetch(url, { method: "POST" })

  if (!response.ok) {
    if (response.status === 409) {
      const payload = (await response.json()) as {
        detail: string
        job: DocumentParseJob
        uploaded_file: {
          id: string
          original_filename: string
          content_type: string | null
          byte_size: number
          status: string
        }
      }
      throw {
        status: 409,
        detail: payload.detail,
        job: payload.job,
        uploadedFile: payload.uploaded_file,
      } as DocumentParseConflictError
    }

    throw await parseErrorResponse(response)
  }

  return response.json() as Promise<DocumentParseJob>
}

export function getDocumentParseJob(jobId: string): Promise<DocumentParseJob> {
  return apiGet<DocumentParseJob>(`/document-parse-jobs/${jobId}`)
}

export function getParsedDocumentForUpload(uploadId: string): Promise<ParsedDocument> {
  return apiGet<ParsedDocument>(`/uploads/${uploadId}/parsed-document`)
}

export function getParsedDocumentSegments(
  parsedDocumentId: string,
  { offset = 0, limit = 20 }: { offset?: number; limit?: number } = {},
): Promise<DocumentSegmentPage> {
  return apiGet<DocumentSegmentPage>(
    `/parsed-documents/${parsedDocumentId}/segments?offset=${offset}&limit=${limit}`,
  )
}