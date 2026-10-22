import { describe, expect, it } from "vitest"

import { isValidEmail, passwordIssues } from "../passwordPolicy"

describe("passwordIssues（与后端密码策略一致）", () => {
  // 测试：满足 10–128 字符、含字母与数字、不等于邮箱的密码没有问题。
  it("合规密码返回空列表", () => {
    expect(passwordIssues("abcdefghi1", "someone@example.com")).toEqual([])
    expect(passwordIssues("a1".repeat(64), "someone@example.com")).toEqual([])
  })

  // 测试：每条未满足的规则都给出可读中文说明，便于在注册与改密表单逐项提示。
  it.each([
    ["abcdefgh1", "10"],
    ["a1".repeat(64) + "x", "128"],
    ["onlyletterspassword", "数字"],
    ["1234567890123", "字母"],
    ["Alice2026@Example.com", "邮箱"],
    ["ALICE2026PW", "邮箱"],
  ])("密码 %s 不合规且说明包含“%s”", (password, fragment) => {
    const email = password.includes("@")
      ? "alice2026@example.com"
      : "alice2026pw@example.com"
    const issues = passwordIssues(password, email)
    expect(issues.join("；")).toContain(fragment)
  })
})

describe("isValidEmail", () => {
  // 测试：前端邮箱预校验与后端规则一致（去空白、需包含 @ 与域名点）。
  it("接受常规邮箱、拒绝明显错误的邮箱", () => {
    expect(isValidEmail(" user@example.com ")).toBe(true)
    expect(isValidEmail("user@localhost")).toBe(false)
    expect(isValidEmail("no-at-sign")).toBe(false)
    expect(isValidEmail("a b@example.com")).toBe(false)
  })
})
