import { traceManager } from "../shared/logger/trace-context"

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api"
const TRACE_HEADER = "X-Trace-ID"

function buildApiUrl(path: string): string {
  const baseUrl = API_BASE_URL.replace(/\/$/, "")
  const normalizedPath = path.startsWith("/") ? path : `/${path}`
  return `${baseUrl}${normalizedPath}`
}

/** Return common headers including X-Trace-ID for every API request. */
function commonHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    Accept: "application/json",
  }
  try {
    headers[TRACE_HEADER] = traceManager.getTraceId()
  } catch {
    // traceManager not yet initialized — omit header gracefully.
  }
  return headers
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(buildApiUrl(path), {
    headers: commonHeaders(),
  })

  if (!response.ok) {
    throw new Error(`请求失败：${response.status}`)
  }

  return response.json() as Promise<T>
}

export async function apiPostForm<T>(path: string, body: FormData): Promise<T> {
  const response = await fetch(buildApiUrl(path), {
    method: "POST",
    body,
    headers: commonHeaders(),
  })

  if (!response.ok) {
    throw new Error(await getErrorMessage(response))
  }

  return response.json() as Promise<T>
}

async function getErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown }
    if (typeof payload.detail === "string" && payload.detail.length > 0) {
      return payload.detail
    }
  } catch {
    // Fall through to the status-based message when the server response is not JSON.
  }

  return `请求失败：${response.status}`
}
