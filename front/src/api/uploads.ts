import { apiPostForm } from "./client"

export interface UploadedFile {
  id: string
  owner_user_id: string
  original_filename: string
  content_type: string | null
  byte_size: number
  storage_key: string
  checksum_sha256: string | null
  status: "stored" | "failed" | "deleted"
  error_message: string | null
  deleted_at: string | null
  created_at: string
  updated_at: string
}

export function uploadFile(file: File): Promise<UploadedFile> {
  const formData = new FormData()
  formData.append("file", file)

  return apiPostForm<UploadedFile>("/uploads", formData)
}
