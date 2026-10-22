export function isValidEmail(raw: string): boolean {
  const email = raw.trim()
  return email.length <= 254 && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)
}

export function passwordIssues(password: string, rawEmail: string): string[] {
  const issues: string[] = []
  const email = rawEmail.trim().toLowerCase()
  const length = Array.from(password).length
  if (length < 10 || length > 128) issues.push("密码长度须为 10–128 个字符")
  if (!/\p{L}/u.test(password) || !/[\p{Nd}\p{Nl}\p{No}]/u.test(password))
    issues.push("密码须同时包含字母和数字")
  if ([email, email.split("@")[0]].includes(password.toLowerCase()))
    issues.push("密码不能与邮箱或邮箱用户名相同")
  return issues
}
