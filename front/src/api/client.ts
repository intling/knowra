const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api"

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
    throw new Error(`请求失败：${response.status}`)
  }

  return response.json() as Promise<T>
}

export async function apiPostForm<T>(path: string, body: FormData): Promise<T> {
  const response = await fetch(buildApiUrl(path), {
    method: "POST",
    body,
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
