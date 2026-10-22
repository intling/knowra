import { readdirSync, readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

import { describe, expect, it } from "vitest"

const API_DIR = dirname(fileURLToPath(import.meta.url))

describe("API 层约束", () => {
  // 测试：src/api 中除 client.ts 外不得直接调用 fetch(，保证 Cookie 与 401 处理统一生效。
  it("业务 API 模块不直接调用 fetch", () => {
    const offenders = readdirSync(API_DIR)
      .filter(
        (name) =>
          name.endsWith(".ts") &&
          !name.endsWith(".test.ts") &&
          name !== "client.ts",
      )
      .filter((name) =>
        /\bfetch\(/.test(readFileSync(join(API_DIR, name), "utf-8")),
      )

    expect(
      offenders,
      `以下模块绕过了 client.ts：${offenders.join(", ")}`,
    ).toEqual([])
  })
})
