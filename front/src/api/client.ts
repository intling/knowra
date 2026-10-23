import { createLogger, getRingBuffer } from "../shared/logger"
import { traceManager } from "../shared/logger/trace-context"

let _logger: ReturnType<typeof createLogger> | null = null
function log() {
  if (!_logger) _logger = createLogger("api:client", getRingBuffer())
  return _logger
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api"
export function buildApiUrl(path: string): string {
  return `${API_BASE_URL.replace(/\/$/, "")}${path.startsWith("/") ? path : `/${path}`}`
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string | null,
    public detail: string,
    public traceId: string | null = null,
  ) {
    super(detail)
    this.name = "ApiError"
  }
}

type RequestOptions = RequestInit & { skipAuthRedirect?: boolean }
let unauthorizedHandler: (() => void) | null = null
export function setUnauthorizedHandler(handler: (() => void) | null) {
  unauthorizedHandler = handler
}

export async function apiFetch(
  path: string,
  options: RequestOptions = {},
): Promise<Response> {
  const { skipAuthRedirect, ...init } = options
  const headers: Record<string, string> = { Accept: "application/json" }
  try {
    headers["X-Trace-ID"] = traceManager.getTraceId()
  } catch {
    /* Logger may not be initialized. */
  }
  Object.assign(
    headers,
    init.headers instanceof Headers
      ? Object.fromEntries(init.headers)
      : init.headers,
  )
  const response = await fetch(buildApiUrl(path), {
    ...init,
    credentials: "include",
    headers,
  })
  if (
    response.status === 401 &&
    !skipAuthRedirect &&
    !path.replace(/^\//, "").startsWith("auth/")
  ) {
    unauthorizedHandler?.()
  }
  log().debug("API 请求完成", {
    path: path.split("?")[0],
    status: response.status,
  })
  return response
}

async function readResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `请求失败：${response.status}`
    let code: string | null = null
    try {
      const body = (await response.json()) as {
        detail?: unknown
        code?: string
      }
      if (typeof body.detail === "string" && body.detail) detail = body.detail
      else if (
        Array.isArray(body.detail) &&
        typeof body.detail[0]?.msg === "string"
      )
        detail = body.detail[0].msg
      code = body.code ?? null
    } catch {
      /* A proxy can return a non-JSON error body. */
    }
    throw new ApiError(
      response.status,
      code,
      detail,
      response.headers?.get?.("X-Trace-ID") ?? null,
    )
  }
  return response.status === 204
    ? (undefined as T)
    : (response.json() as Promise<T>)
}

export async function apiGet<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  return readResponse<T>(await apiFetch(path, options))
}

export async function apiPostForm<T>(path: string, body: FormData): Promise<T> {
  return readResponse<T>(await apiFetch(path, { method: "POST", body }))
}

async function writeJson<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  return readResponse<T>(
    await apiFetch(path, {
      method,
      headers: { "Content-Type": "application/json" },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    }),
  )
}

export function apiPostJson<T = void>(
  path: string,
  body?: unknown,
): Promise<T> {
  return writeJson<T>("POST", path, body)
}
export function apiPatchJson<T>(path: string, body: unknown): Promise<T> {
  return writeJson<T>("PATCH", path, body)
}

export function apiPutJson<T>(path: string, body: unknown): Promise<T> {
  return writeJson<T>("PUT", path, body)
}

export function apiDelete(path: string): Promise<void> {
  return writeJson<void>("DELETE", path)
}
