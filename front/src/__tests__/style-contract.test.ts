// @vitest-environment node
/**
 * 样式契约测试：用真实的 Tailwind v4 编译器编译 `src/style.css`，
 * 再用 lightningcss 展开嵌套，断言「编译产物」而不是源码字符串。
 *
 * 能捕获的回归：
 * - 字体令牌命名错误导致 `font-display` 等工具类不产生 font-family（历史 bug）
 * - `prose-knowra` 未声明列表样式，导致浏览器中 ol/ul 的 list-style-type 为 none（历史 bug）
 * - 字体栈退回 Inter/Roboto/Arial 或缺少中文回退
 * - 缺失减少动画偏好支持
 * - 重新引入外网字体依赖
 */
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

import { transform } from "lightningcss"
import { compile } from "tailwindcss"
import { beforeAll, describe, expect, it } from "vitest"

const here = path.dirname(fileURLToPath(import.meta.url))
const frontRoot = path.resolve(here, "../..")
const srcDir = path.join(frontRoot, "src")
const twDir = path.join(frontRoot, "node_modules/tailwindcss")

/** 编译 style.css，生成指定候选类名的 CSS，并展开嵌套为平铺规则。 */
async function buildCss(candidates: string[]): Promise<string> {
  const source = fs.readFileSync(path.join(srcDir, "style.css"), "utf8")
  const compiler = await compile(source, {
    base: srcDir,
    loadStylesheet: async (id: string) => {
      const rel = id === "tailwindcss" ? "index.css" : id.replace(/^tailwindcss\//, "")
      const file = path.join(twDir, rel)
      return { path: file, base: path.dirname(file), content: fs.readFileSync(file, "utf8") }
    },
  })
  const raw = compiler.build(candidates)
  const { code } = transform({
    filename: "style.css",
    code: Buffer.from(raw),
    // 以 Chrome 100 为目标，强制把 CSS 嵌套展开为平铺选择器，便于断言
    targets: { chrome: 100 << 16 },
  })
  return code.toString()
}

/** 读取编译产物中某个 CSS 自定义属性的值。 */
function readVar(css: string, name: string): string | null {
  const match = css.match(new RegExp(`${name}:\\s*([^;]+);`))
  return match ? match[1]!.trim() : null
}

/** 找出选择器列表中包含目标选择器（完全匹配）的全部声明块并拼接。 */
function declarationsFor(css: string, selector: string): string {
  const blocks: string[] = []
  for (const m of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selectors = m[1]!.split(",").map((s) => s.trim().replace(/\s+/g, " "))
    if (selectors.includes(selector)) blocks.push(m[2]!)
  }
  return blocks.join(";")
}

let css = ""

beforeAll(async () => {
  css = await buildCss([
    "font-display",
    "font-sans",
    "font-mono",
    "prose-knowra",
    "bg-paper",
    "bg-paper-deep",
    "bg-surface",
    "text-ink",
    "text-ink-muted",
    "text-ink-faint",
    "border-line",
    "text-cite",
    "bg-brand-700",
    "paper-atmosphere",
  ])
})

describe("字体令牌（Tailwind v4 命名空间）", () => {
  // 验证 font-display 工具类真实生成 font-family，修复 --font-family-* 命名导致令牌失效的问题
  it("font-display 工具类输出 font-family: var(--font-display)", () => {
    expect(declarationsFor(css, ".font-display")).toContain("font-family: var(--font-display)")
  })

  // 验证 font-mono 工具类同样生效（历史上同样因命名错误失效）
  it("font-mono 工具类输出 font-family: var(--font-mono)", () => {
    expect(declarationsFor(css, ".font-mono")).toContain("font-family: var(--font-mono)")
  })

  // 验证标题字体栈包含中文衬线回退并以通用 serif 结尾，离线也能读
  it("--font-display 含中文衬线字体并以 serif 兜底", () => {
    const value = readVar(css, "--font-display")
    expect(value, "编译产物中未定义 --font-display，标题字体令牌不会生效").not.toBeNull()
    expect(value!).toMatch(/Songti SC|Noto Serif SC|Source Han Serif SC|STSong|SimSun/)
    expect(value!.trim().endsWith("serif")).toBe(true)
  })

  // 验证正文字体栈包含中文无衬线回退并以通用 sans-serif 结尾
  it("--font-sans 含中文无衬线字体并以 sans-serif 兜底", () => {
    const value = readVar(css, "--font-sans")
    expect(value, "编译产物中未定义 --font-sans").not.toBeNull()
    expect(value!).toMatch(/PingFang SC|Microsoft YaHei|Noto Sans SC|Hiragino Sans GB/)
    expect(value!.trim().endsWith("sans-serif")).toBe(true)
  })

  // 验证设计约束：字体栈不使用默认的 Inter / Roboto / Arial
  it("显示、正文与等宽字体栈均不包含 Inter、Roboto、Arial", () => {
    for (const name of ["--font-display", "--font-sans", "--font-mono"]) {
      const value = readVar(css, name) ?? ""
      expect(value, `${name} 不应包含 Inter/Roboto/Arial，实际为：${value}`).not.toMatch(
        /\bInter\b|\bRoboto\b|\bArial\b/,
      )
    }
  })
})

describe("语义色彩令牌", () => {
  // 验证新视觉语言的语义令牌可作为 Tailwind 工具类使用（否则组件中的类名不会生成样式）
  it.each([
    [".bg-paper", "background-color"],
    [".bg-paper-deep", "background-color"],
    [".bg-surface", "background-color"],
    [".text-ink", "color"],
    [".text-ink-muted", "color"],
    [".text-ink-faint", "color"],
    [".border-line", "border-color"],
    [".text-cite", "color"],
  ])("%s 生成 %s 声明", (selector, property) => {
    expect(declarationsFor(css, selector), `${selector} 未生成样式，说明语义令牌缺失`).toContain(
      `${property}:`,
    )
  })
})

describe("纸面氛围", () => {
  // 验证主对话区有极低对比度的径向渐变氛围（同色板、无图片），而非纯平底色
  it("paper-atmosphere 在纸色底上叠加径向渐变且不引用图片文件", () => {
    const decl = declarationsFor(css, ".paper-atmosphere")
    expect(decl).toContain("radial-gradient")
    expect(decl).toMatch(/background-color/)
    expect(decl).not.toMatch(/url\(/)
  })
})

describe("prose-knowra 回答排版", () => {
  // 验证无序列表恢复圆点标记（浏览器实测此前为 list-style-type: none）
  it("ul 使用 list-style-type: disc", () => {
    expect(declarationsFor(css, ".prose-knowra ul")).toContain("list-style-type: disc")
  })

  // 验证有序列表恢复数字序号
  it("ol 使用 list-style-type: decimal", () => {
    expect(declarationsFor(css, ".prose-knowra ol")).toContain("list-style-type: decimal")
  })

  // 验证列表有左内边距，否则标记会被裁到容器外
  it("ul / ol 设置左内边距以容纳列表标记", () => {
    expect(declarationsFor(css, ".prose-knowra ul")).toMatch(/padding-left|padding-inline-start/)
    expect(declarationsFor(css, ".prose-knowra ol")).toMatch(/padding-left|padding-inline-start/)
  })

  // 验证表格单元格有分隔线，窄屏可横向滚动不撑破页面
  it("表格单元格有边框且表格可横向滚动", () => {
    expect(declarationsFor(css, ".prose-knowra td")).toMatch(/border-bottom/)
    expect(declarationsFor(css, ".prose-knowra table")).toContain("overflow-x: auto")
  })

  // 验证代码块可横向滚动
  it("pre 代码块可横向滚动", () => {
    expect(declarationsFor(css, ".prose-knowra pre")).toContain("overflow-x: auto")
  })
})

describe("可访问性基础", () => {
  // 验证全局尊重用户的减少动画偏好
  it("包含 prefers-reduced-motion: reduce 媒体查询并压缩过渡时长", () => {
    const block = css.match(/@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*?)\}\s*\}/)
    expect(block, "未找到 prefers-reduced-motion 规则").not.toBeNull()
    expect(block![1]).toMatch(/transition-duration/)
    expect(block![1]).toMatch(/animation-duration/)
  })
})

describe("入口 HTML", () => {
  // 验证页面不依赖外网字体服务，离线或受限网络下也能正常阅读
  it("index.html 不引用外部字体服务", () => {
    const html = fs.readFileSync(path.join(frontRoot, "index.html"), "utf8")
    const hrefs = [...html.matchAll(/<link[^>]+href="([^"]+)"/g)].map((m) => m[1]!)
    const external = hrefs.filter((h) => /fonts\.googleapis\.com|fonts\.gstatic\.com/.test(h))
    expect(external, `仍引用外网字体：${external.join(", ")}`).toEqual([])
  })
})
