export function sanitizeRedirect(raw: unknown): string {
  if (typeof raw !== "string") return "/"
  let decoded: string
  try {
    decoded = decodeURIComponent(raw)
  } catch {
    return "/"
  }
  if (
    !decoded.startsWith("/") ||
    decoded.startsWith("//") ||
    decoded.includes("\\") ||
    Array.from(decoded).some(
      (char) => char.charCodeAt(0) <= 32 || char.charCodeAt(0) === 127,
    )
  )
    return "/"
  const path = decoded.split(/[?#]/)[0]?.replace(/\/+$/, "").toLowerCase()
  if (path === "/login" || path === "/register") return "/"
  return raw
}
