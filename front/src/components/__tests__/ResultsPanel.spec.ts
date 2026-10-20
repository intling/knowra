import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import { makeResult } from "../../__tests__/fixtures/search"
import ResultsPanel from "../ResultsPanel.vue"

async function barWidths(scores: number[]) {
  const results = scores.map((score, i) =>
    makeResult({ rank: i + 1, chunk_id: `c${i}`, score }),
  )
  const wrapper = mount(ResultsPanel, { props: { results } })
  await wrapper.find('[data-testid="results-toggle"]').trigger("click")
  const bars = wrapper.findAll('[data-testid="result-score-bar"]')
  expect(bars.length, "每条结果都应渲染 data-testid=result-score-bar 的分数条").toBe(scores.length)
  return wrapper
    .findAll('[data-testid="result-score-bar"]')
    .map((bar) => (bar.element as HTMLElement).style.width)
}

describe("ResultsPanel 相似度分数条", () => {
  // 验证分数条按相似度（1 − 余弦距离）计算：距离 0.2 → 80%
  it("距离 0.2 的分数条宽度为 80%", async () => {
    expect(await barWidths([0.2])).toEqual(["80%"])
  })

  // 验证距离最大的结果不再显示为空条（旧实现按相对最大值计算，最差结果恒为 0%）
  it("距离 0.2 与 0.6 分别为 80% 与 40%", async () => {
    expect(await barWidths([0.2, 0.6])).toEqual(["80%", "40%"])
  })

  // 验证宽度限制在 0–100%：距离 > 1 为 0%，负距离为 100%
  it("超出范围的距离被限制在 0% 到 100%", async () => {
    expect(await barWidths([-0.1, 1.2])).toEqual(["100%", "0%"])
  })
})
