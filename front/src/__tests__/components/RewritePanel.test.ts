import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import type { RewriteInfo, RewrittenQuery } from "../../api/search"

// ── Test fixtures ─────────────────────────────────────────────────────────

/** Full RewriteInfo payload with rewritten_queries. */
const FULL_REWRITE_INFO: RewriteInfo = {
  original_query: "它怎么用",
  rewritten_queries: [
    { query: "Python 怎么使用", strategy: "context_fusion" },
    { query: "Python 如何使用指南", strategy: "normalize" },
  ] as RewrittenQuery[],
  strategies_used: ["context_fusion", "normalize"],
  rewrite_time_ms: 320.5,
  cache_hit: false,
}

/** RewriteInfo with cache hit (no LLM call). */
const CACHE_HIT_REWRITE_INFO: RewriteInfo = {
  original_query: "Python 怎么使用",
  rewritten_queries: [
    { query: "Python 怎么使用", strategy: null },
  ] as RewrittenQuery[],
  strategies_used: [],
  rewrite_time_ms: 2.1,
  cache_hit: true,
}

/** RewriteInfo with empty rewritten_queries. */
const EMPTY_QUERIES_REWRITE_INFO: RewriteInfo = {
  original_query: "简单查询",
  rewritten_queries: [] as RewrittenQuery[],
  strategies_used: [],
  rewrite_time_ms: 0.0,
  cache_hit: true,
}

/** RewriteInfo with rewrite error. */
const ERROR_REWRITE_INFO: RewriteInfo = {
  original_query: "失败查询",
  rewritten_queries: [] as RewrittenQuery[],
  strategies_used: [],
  rewrite_time_ms: 0.0,
  cache_hit: false,
  error: "Query rewriter timeout",
}

// ── Lazy import (component may not exist yet — TDD red test) ──────────────

async function getRewritePanel() {
  const module = await import(
    /* @vite-ignore */ "../../components/RewritePanel.vue"
  )
  return module.default
}

// ── Tests ─────────────────────────────────────────────────────────────────

describe("RewritePanel", () => {
  // ── 显示/隐藏逻辑 ──────────────────────────────────────────────────────

  describe("display toggle (show/hide)", () => {
    it("always renders the panel (even with empty rewritten_queries)", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: FULL_REWRITE_INFO },
      })

      // Panel should be in the DOM
      expect(wrapper.find('[data-testid="rewrite-panel"]').exists()).toBe(true)
      // The toggle button should be visible
      expect(
        wrapper.find('[data-testid="rewrite-toggle"]').exists(),
      ).toBe(true)
    })

    it("renders with empty rewritten_queries (always visible, shows empty state)", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: EMPTY_QUERIES_REWRITE_INFO },
      })

      // Panel should always render, even when there are no rewritten queries
      expect(wrapper.find('[data-testid="rewrite-panel"]').exists()).toBe(true)
      // Toggle should be visible
      expect(
        wrapper.find('[data-testid="rewrite-toggle"]').exists(),
      ).toBe(true)
    })
  })

  // ── 默认折叠状态 ───────────────────────────────────────────────────────

  describe("default collapsed state", () => {
    it("is collapsed by default (expanded content not visible)", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: FULL_REWRITE_INFO },
      })

      // The toggle button should be visible
      expect(
        wrapper.find('[data-testid="rewrite-toggle"]').exists(),
      ).toBe(true)
      // But the expanded content should NOT be visible initially
      expect(
        wrapper.find('[data-testid="rewrite-content"]').exists(),
      ).toBe(false)
    })
  })

  // ── 折叠/展开交互 ──────────────────────────────────────────────────────

  describe("collapse/expand toggle", () => {
    it("expands content when toggle button is clicked", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: FULL_REWRITE_INFO },
      })

      // Initially collapsed
      expect(
        wrapper.find('[data-testid="rewrite-content"]').exists(),
      ).toBe(false)

      // Click the toggle button
      await wrapper
        .find('[data-testid="rewrite-toggle"]')
        .trigger("click")

      // Now expanded content should be visible
      expect(
        wrapper.find('[data-testid="rewrite-content"]').exists(),
      ).toBe(true)
    })

    it("collapses content when toggle button is clicked again", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: FULL_REWRITE_INFO },
      })

      // Expand first
      await wrapper
        .find('[data-testid="rewrite-toggle"]')
        .trigger("click")
      expect(
        wrapper.find('[data-testid="rewrite-content"]').exists(),
      ).toBe(true)

      // Click again to collapse
      await wrapper
        .find('[data-testid="rewrite-toggle"]')
        .trigger("click")
      expect(
        wrapper.find('[data-testid="rewrite-content"]').exists(),
      ).toBe(false)
    })
  })

  // ── 原始查询展示 ───────────────────────────────────────────────────────

  describe("original query display", () => {
    it("shows original query with italic muted style when expanded", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: FULL_REWRITE_INFO },
      })

      // Expand
      await wrapper
        .find('[data-testid="rewrite-toggle"]')
        .trigger("click")

      const originalQuery = wrapper.find(
        '[data-testid="original-query"]',
      )
      expect(originalQuery.exists()).toBe(true)
      expect(originalQuery.text()).toContain("它怎么用")
      // Visual style: text-sm text-neutral-500 italic
      expect(originalQuery.classes()).toContain("text-sm")
      expect(originalQuery.classes()).toContain("text-neutral-500")
      expect(originalQuery.classes()).toContain("italic")
    })
  })

  // ── 改写结果列表展示 ───────────────────────────────────────────────────

  describe("rewritten queries list", () => {
    it("renders all rewritten queries in a list", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: FULL_REWRITE_INFO },
      })

      // Expand
      await wrapper
        .find('[data-testid="rewrite-toggle"]')
        .trigger("click")

      const queryItems = wrapper.findAll(
        '[data-testid="rewritten-query-item"]',
      )
      expect(queryItems).toHaveLength(2)
    })

    it("each rewritten query displays strategy tag and query text", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: FULL_REWRITE_INFO },
      })

      // Expand
      await wrapper
        .find('[data-testid="rewrite-toggle"]')
        .trigger("click")

      const queryItems = wrapper.findAll(
        '[data-testid="rewritten-query-item"]',
      )

      // First item
      const firstText = queryItems[0]!.find(
        '[data-testid="rewritten-query-text"]',
      )
      expect(firstText.exists()).toBe(true)
      expect(firstText.text()).toBe("Python 怎么使用")

      const firstTag = queryItems[0]!.find(
        '[data-testid="strategy-tag"]',
      )
      expect(firstTag.exists()).toBe(true)
      // context_fusion → "上下文融合"
      expect(firstTag.text()).toContain("上下文融合")

      // Second item
      const secondText = queryItems[1]!.find(
        '[data-testid="rewritten-query-text"]',
      )
      expect(secondText.text()).toBe("Python 如何使用指南")

      const secondTag = queryItems[1]!.find(
        '[data-testid="strategy-tag"]',
      )
      expect(secondTag.exists()).toBe(true)
      // normalize → "规范重述"
      expect(secondTag.text()).toContain("规范重述")
    })

    it("handles strategy=null by showing a default label", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: CACHE_HIT_REWRITE_INFO },
      })

      await wrapper
        .find('[data-testid="rewrite-toggle"]')
        .trigger("click")

      const tag = wrapper.find('[data-testid="strategy-tag"]')
      expect(tag.exists()).toBe(true)
      // null strategy should show some default/fallback text
      expect(tag.text().length).toBeGreaterThan(0)
    })

    it("list items are separated by divide-y divider", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: FULL_REWRITE_INFO },
      })

      await wrapper
        .find('[data-testid="rewrite-toggle"]')
        .trigger("click")

      const list = wrapper.find('[data-testid="rewritten-queries-list"]')
      expect(list.exists()).toBe(true)
      expect(list.classes()).toContain("divide-y")
      expect(list.classes()).toContain("divide-neutral-100")
    })
  })

  // ── 性能指标展示 ───────────────────────────────────────────────────────

  describe("performance metrics", () => {
    it("shows rewrite time in milliseconds", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: FULL_REWRITE_INFO },
      })

      await wrapper
        .find('[data-testid="rewrite-toggle"]')
        .trigger("click")

      const timeEl = wrapper.find('[data-testid="rewrite-time"]')
      expect(timeEl.exists()).toBe(true)
      // Should show the time value in ms
      expect(timeEl.text()).toContain("320.5")
      expect(timeEl.text()).toMatch(/ms/)
      // Visual style: text-xs text-neutral-400
      expect(timeEl.classes()).toContain("text-xs")
      expect(timeEl.classes()).toContain("text-neutral-400")
    })

    it("shows cache hit status with emerald style when cache_hit is true", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: CACHE_HIT_REWRITE_INFO },
      })

      await wrapper
        .find('[data-testid="rewrite-toggle"]')
        .trigger("click")

      const cacheEl = wrapper.find('[data-testid="cache-hit"]')
      expect(cacheEl.exists()).toBe(true)
      // Should use emerald-500 color for cache hit
      expect(cacheEl.classes()).toContain("text-emerald-500")
    })

    it("shows cache miss in muted style when cache_hit is false", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: FULL_REWRITE_INFO },
      })

      await wrapper
        .find('[data-testid="rewrite-toggle"]')
        .trigger("click")

      const cacheEl = wrapper.find('[data-testid="cache-hit"]')
      expect(cacheEl.exists()).toBe(true)
      // Cache miss should NOT have emerald-500
      expect(cacheEl.classes()).not.toContain("text-emerald-500")
    })
  })

  // ── 视觉样式一致性（与 PromptPreview 保持一致）─────────────────────────

  describe("visual consistency with PromptPreview", () => {
    it("toggle button uses consistent flex layout with hover effect", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: FULL_REWRITE_INFO },
      })

      const toggle = wrapper.find('[data-testid="rewrite-toggle"]')
      expect(toggle.exists()).toBe(true)

      // Same layout classes as PromptPreview toggle
      expect(toggle.classes()).toContain("flex")
      expect(toggle.classes()).toContain("w-full")
      expect(toggle.classes()).toContain("items-center")
      expect(toggle.classes()).toContain("justify-between")
      expect(toggle.classes()).toContain("px-5")
      expect(toggle.classes()).toContain("py-3")
      expect(toggle.classes()).toContain("text-left")
      expect(toggle.classes()).toContain("transition")
      expect(toggle.classes()).toContain("hover:bg-neutral-50")
    })

    it("title uses font-display text-sm font-semibold text-neutral-700", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: FULL_REWRITE_INFO },
      })

      const title = wrapper.find('[data-testid="rewrite-title"]')
      expect(title.exists()).toBe(true)
      expect(title.text()).toBe("查询重写详情")

      // Same typography classes as PromptPreview title
      expect(title.classes()).toContain("font-display")
      expect(title.classes()).toContain("text-sm")
      expect(title.classes()).toContain("font-semibold")
      expect(title.classes()).toContain("text-neutral-700")
    })

    it("chevron SVG has size-4 text-neutral-400 transition-transform classes", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: FULL_REWRITE_INFO },
      })

      const chevron = wrapper.find('[data-testid="rewrite-chevron"]')
      expect(chevron.exists()).toBe(true)

      // Same SVG styling as PromptPreview chevron
      expect(chevron.classes()).toContain("size-4")
      expect(chevron.classes()).toContain("text-neutral-400")
      expect(chevron.classes()).toContain("transition-transform")
    })

    it("chevron rotates 180 degrees when expanded", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: FULL_REWRITE_INFO },
      })

      const chevron = wrapper.find('[data-testid="rewrite-chevron"]')

      // Initially collapsed — no rotate-180
      expect(chevron.classes()).not.toContain("rotate-180")

      // Expand
      await wrapper
        .find('[data-testid="rewrite-toggle"]')
        .trigger("click")

      // Now rotated
      expect(chevron.classes()).toContain("rotate-180")
    })
  })

  // ── 改写条数徽章 ───────────────────────────────────────────────────────

  describe("rewrite count badge", () => {
    it("shows rewrite count badge with correct count", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: FULL_REWRITE_INFO },
      })

      const badge = wrapper.find('[data-testid="rewrite-count-badge"]')
      expect(badge.exists()).toBe(true)
      expect(badge.text()).toContain("2")

      // Badge styling
      expect(badge.classes()).toContain("rounded-full")
    })
  })

  // ── 边界情况 ────────────────────────────────────────────────────────────

  describe("edge cases", () => {
    it("handles single rewritten query correctly", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: CACHE_HIT_REWRITE_INFO },
      })

      await wrapper
        .find('[data-testid="rewrite-toggle"]')
        .trigger("click")

      const queryItems = wrapper.findAll(
        '[data-testid="rewritten-query-item"]',
      )
      expect(queryItems).toHaveLength(1)
    })

    it("renders empty state when rewrite_time_ms is 0 and rewritten_queries is empty", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: EMPTY_QUERIES_REWRITE_INFO },
      })

      // Panel should always render
      expect(wrapper.find('[data-testid="rewrite-panel"]').exists()).toBe(true)

      // Expand to see empty state
      await wrapper
        .find('[data-testid="rewrite-toggle"]')
        .trigger("click")

      // Empty state message should be visible
      const emptyState = wrapper.find('[data-testid="rewrite-empty-state"]')
      expect(emptyState.exists()).toBe(true)
      const emptyMsg = wrapper.find('[data-testid="rewrite-empty-message"]')
      expect(emptyMsg.exists()).toBe(true)
    })

    it("handles strategies_used as empty array gracefully", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: CACHE_HIT_REWRITE_INFO },
      })

      await wrapper
        .find('[data-testid="rewrite-toggle"]')
        .trigger("click")

      // Component should not crash when strategies_used is empty
      expect(
        wrapper.find('[data-testid="rewrite-content"]').exists(),
      ).toBe(true)
    })

    it("shows error message in empty state when rewrite error is present", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: ERROR_REWRITE_INFO },
      })

      await wrapper
        .find('[data-testid="rewrite-toggle"]')
        .trigger("click")

      // Should show empty state (no rewritten_queries)
      const emptyState = wrapper.find('[data-testid="rewrite-empty-state"]')
      expect(emptyState.exists()).toBe(true)

      // Error message should be contained
      const emptyMsg = wrapper.find('[data-testid="rewrite-empty-message"]')
      expect(emptyMsg.exists()).toBe(true)
      expect(emptyMsg.text()).toContain("Query rewriter timeout")
    })

    it("always shows original query even when rewritten_queries is empty", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: EMPTY_QUERIES_REWRITE_INFO },
      })

      await wrapper
        .find('[data-testid="rewrite-toggle"]')
        .trigger("click")

      // Original query should always be visible
      const originalQuery = wrapper.find('[data-testid="original-query"]')
      expect(originalQuery.exists()).toBe(true)
      expect(originalQuery.text()).toContain("简单查询")
    })
  })
})
