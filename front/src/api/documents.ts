import { ApiError, apiGet, apiPostJson } from "./client"

export interface SourceFile {
  id: string
  original_filename: string
  content_type: string | null
  byte_size: number
  status: string
}

export interface DocumentRecord {
  id: string
  owner_user_id: string
  uploaded_file_id: string
  title: string
  source_content_type: string | null
  parser_name: string | null
  parser_version: string | null
  chunker_name: string | null
  chunker_version: string | null
  tokenizer_name: string | null
  tokenizer_version: string | null
  status: "parsed" | "failed"
  chunk_count: number
  total_chars: number
  content_sha256: string | null
  metadata_json: Record<string, unknown>
  error_message: string | null
  deleted_at: string | null
  created_at: string
  updated_at: string
  source_file: SourceFile | null
}

export interface DocumentChunk {
  id: string
  document_id: string
  owner_user_id: string
  chunk_index: number
  content: string
  content_sha256: string
  char_start: number
  char_end: number
  token_count: number
  source_locator_json: Record<string, unknown>
  metadata_json: Record<string, unknown>
  created_at: string
  updated_at: string
}

export class DocumentConflictError extends Error {
  constructor(readonly existingDocument: DocumentRecord) {
    super("Document already exists")
    this.name = "DocumentConflictError"
  }
}

export function listDocuments(): Promise<DocumentRecord[]> {
  return apiGet<DocumentRecord[]>("/documents")
}

export async function createDocument(uploadedFileId: string): Promise<DocumentRecord> {
  try {
    return await apiPostJson<DocumentRecord>("/documents", {
      uploaded_file_id: uploadedFileId,
    })
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      const existingDocument = getExistingDocument(error.payload)
      if (existingDocument) {
        throw new DocumentConflictError(existingDocument)
      }
    }

    throw error
  }
}

export function listDocumentChunks(documentId: string): Promise<DocumentChunk[]> {
  return apiGet<DocumentChunk[]>(`/documents/${documentId}/chunks`)
}

function getExistingDocument(payload: unknown): DocumentRecord | null {
  if (!isObject(payload) || !isObject(payload.existing_document)) {
    return null
  }

  if (
    typeof payload.existing_document.id !== "string" ||
    typeof payload.existing_document.title !== "string" ||
    typeof payload.existing_document.uploaded_file_id !== "string"
  ) {
    return null
  }

  return payload.existing_document as unknown as DocumentRecord
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}
