const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api"

function buildApiUrl(path: string): string {
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
