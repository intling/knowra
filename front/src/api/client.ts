const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api"

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly payload: unknown,
  ) {
    super(message)
    this.name = "ApiError"
  }
}

export function buildApiUrl(path: string): string {
  const baseUrl = API_BASE_URL.replace(/\/$/, "")
  const normalizedPath = path.startsWith("/") ? path : `/${path}`
  return `${baseUrl}${normalizedPath}`
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(buildApiUrl(path), {
    headers: {
      Accept: "application/json",
    },
  })

  if (!response.ok) {
    throw await getApiError(response)
  }

  return response.json() as Promise<T>
}

export async function apiPostJson<T>(
  path: string,
  body: Record<string, unknown>,
): Promise<T> {
  const response = await fetch(buildApiUrl(path), {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    throw await getApiError(response)
  }

  return response.json() as Promise<T>
}

export async function apiPostForm<T>(path: string, body: FormData): Promise<T> {
  const response = await fetch(buildApiUrl(path), {
    method: "POST",
    body,
  })

  if (!response.ok) {
    throw await getApiError(response)
  }

  return response.json() as Promise<T>
}

async function getApiError(response: Response): Promise<ApiError> {
  const payload = await getErrorPayload(response)
  return new ApiError(getErrorMessage(response, payload), response.status, payload)
}

async function getErrorPayload(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function getErrorMessage(response: Response, payload: unknown): string {
  if (isObject(payload) && typeof payload.detail === "string" && payload.detail.length > 0) {
    return payload.detail
  }

  return `请求失败：${response.status}`
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}
