/** Decode only the designated public demo identity; credentials stay in form memory. */
export function parseDemoFragment(
  hash: string,
): { email: string; password: string } | null {
  if (!hash.startsWith("#demo=") || hash.length > 2048) return null
  try {
    const params = new URLSearchParams(hash.replace(/^#/, ""))
    const values = params.getAll("demo")
    if (values.length !== 1 || !/^[A-Za-z0-9_-]+={0,2}$/.test(values[0] ?? ""))
      return null
    const decoded: unknown = JSON.parse(
      atob(values[0]!.replace(/-/g, "+").replace(/_/g, "/")),
    )
    if (
      typeof decoded !== "object" ||
      decoded === null ||
      Array.isArray(decoded)
    )
      return null
    const value = decoded as Record<string, unknown>
    if (
      value.email !== "demo@deerfd.com" ||
      typeof value.password !== "string" ||
      !value.password.length ||
      value.password.length > 128
    )
      return null
    return { email: value.email, password: value.password }
  } catch {
    return null
  }
}
