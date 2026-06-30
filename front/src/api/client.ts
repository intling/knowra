import { createLogger, getRingBuffer } from "../shared/logger"
import { traceManager } from "../shared/logger/trace-context"

/** Lazy logger — getRingBuffer() is only available after main.ts initLogger(). */
let _logger: ReturnType<typeof createLogger> | null = null
function log() {
  if (!_logger) _logger = createLogger("api:client", getRingBuffer())
  return _logger
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api"
const TRACE_HEADER = "X-Trace-ID"

export function buildApiUrl(path: string): string {
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
  const start = performance.now()
  const url = buildApiUrl(path)
  log().debug("API GET 请求发送", { path, url })

  let response: Response
  try {
    response = await fetch(url, {
      headers: commonHeaders(),
    })
  } catch (error) {
    log().error("API GET 网络请求失败", error, { path, url })
    throw error
  }

  if (!response.ok) {
    log().warn("API GET 返回非 2xx 状态", {
      path, status: response.status, duration: Math.round(performance.now() - start),
    })
    throw new Error(`请求失败：${response.status}`)
  }

  log().info("API GET 请求完成", {
    path, status: response.status, duration: Math.round(performance.now() - start),
  })
  return response.json() as Promise<T>
}

export async function apiPostForm<T>(path: string, body: FormData): Promise<T> {
  const start = performance.now()
  const url = buildApiUrl(path)
  log().debug("API POST 请求发送", { path, url })

  let response: Response
  try {
    response = await fetch(url, {
      method: "POST",
      body,
      headers: commonHeaders(),
    })
  } catch (error) {
    log().error("API POST 网络请求失败", error, { path, url })
    throw error
  }

  if (!response.ok) {
    log().warn("API POST 返回非 2xx 状态", {
      path, status: response.status, duration: Math.round(performance.now() - start),
    })
    throw new Error(await getErrorMessage(response))
  }

  log().info("API POST 请求完成", {
    path, status: response.status, duration: Math.round(performance.now() - start),
  })
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
