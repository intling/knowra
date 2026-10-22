import { describe, expect, it } from "vitest"

import { sanitizeRedirect } from "../redirect"

describe("sanitizeRedirect", () => {
  // 测试：合法的站内路径（含查询与哈希）原样返回。
  it.each(["/", "/verify", "/account?tab=password", "/admin/users#top"])(
    "保留站内路径 %s",
    (path) => {
      expect(sanitizeRedirect(path)).toBe(path)
    },
  )

  // 测试：外部 URL、协议相对路径、反斜线变体、控制字符、非字符串和认证页本身一律回到站内默认页。
  it.each([
    "https://evil.example",
    "//evil.example",
    "/\\evil.example",
    "\\\\evil.example",
    "/%0d%0aLocation:evil",
    "/foo\nbar",
    "javascript:alert(1)",
    "verify",
    "",
    "/login",
    "/login?redirect=/verify",
    "/register",
  ])("拒绝不安全的返回地址 %s", (raw) => {
    expect(sanitizeRedirect(raw)).toBe("/")
  })

  // 测试：数组或缺省的 query 值回退到默认页。
  it("非字符串输入回到默认页", () => {
    expect(sanitizeRedirect(undefined)).toBe("/")
    expect(sanitizeRedirect(null)).toBe("/")
    expect(sanitizeRedirect(["/verify"])).toBe("/")
  })
})
