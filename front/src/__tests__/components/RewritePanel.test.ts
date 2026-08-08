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

// ── Phase 2 fixtures ────────────────────────────────────────────────────────

/** Phase 2 RewriteInfo with intent, complexity, and multiple strategy types. */
const PHASE2_REWRITE_INFO: RewriteInfo = {
  original_query: "数据库咋优化",
  rewritten_queries: [
    {
      query: "如何优化数据库性能",
      strategy: "normalize",
      duration_ms: 120.5,
      tokens: 45,
    },
    {
      query: "数据库性能调优方法",
      strategy: "term_align",
      duration_ms: 85.2,
      tokens: 32,
    },
    {
      query: "数据库性能优化：索引策略、查询优化、缓存配置、连接池管理",
      strategy: "expand",
      duration_ms: 210.0,
      tokens: 65,
    },
  ] as RewrittenQuery[],
  strategies_used: ["context_fusion", "normalize", "term_align", "expand"],
  rewrite_time_ms: 450.5,
  cache_hit: false,
  intent: "analytical",
  complexity: 7,
  cache_level: null,
}

/** RewriteInfo with context_fusion strategy for teal color verification. */
const CONTEXT_FUSION_ONLY_INFO: RewriteInfo = {
  original_query: "它怎么用",
  rewritten_queries: [
    { query: "Python 怎么使用", strategy: "context_fusion" },
  ] as RewrittenQuery[],
  strategies_used: ["context_fusion"],
  rewrite_time_ms: 200.0,
  cache_hit: false,
}

/** RewriteInfo with L1 cache level. */
const L1_CACHE_LEVEL_INFO: RewriteInfo = {
  original_query: "Python 怎么使用",
  rewritten_queries: [
    { query: "Python 怎么使用", strategy: null },
  ] as RewrittenQuery[],
  strategies_used: [],
  rewrite_time_ms: 2.1,
  cache_hit: true,
  cache_level: "L1",
}

/** RewriteInfo with L2 cache level. */
const L2_CACHE_LEVEL_INFO: RewriteInfo = {
  original_query: "如何配置 Nginx",
  rewritten_queries: [
    { query: "Nginx 配置方法", strategy: "normalize" },
  ] as RewrittenQuery[],
  strategies_used: ["normalize"],
  rewrite_time_ms: 0.3,
  cache_hit: true,
  cache_level: "L2",
}

/** RewriteInfo with an unknown strategy for fallback color verification. */
const UNKNOWN_STRATEGY_INFO: RewriteInfo = {
  original_query: "某个查询",
  rewritten_queries: [
    { query: "某个查询（未知策略处理）", strategy: "some_future_strategy" },
  ] as RewrittenQuery[],
  strategies_used: ["some_future_strategy"],
  rewrite_time_ms: 100.0,
  cache_hit: false,
}

/** RewriteInfo with factual intent and low complexity. */
const FACTUAL_INTENT_INFO: RewriteInfo = {
  original_query: "Redis 默认端口是多少",
  rewritten_queries: [
    { query: "Redis 默认端口是多少", strategy: "direct" },
  ] as RewrittenQuery[],
  strategies_used: [],
  rewrite_time_ms: 5.0,
  cache_hit: false,
  intent: "factual",
  complexity: 1,
}

/** RewriteInfo with no intent/complexity (backward compatibility). */
const NO_INTENT_INFO: RewriteInfo = {
  original_query: "老数据",
  rewritten_queries: [
    { query: "老数据", strategy: "context_fusion" },
  ] as RewrittenQuery[],
  strategies_used: ["context_fusion"],
  rewrite_time_ms: 100.0,
  cache_hit: false,
  // intent and complexity intentionally omitted
}

/** RewriteInfo with missing cache_level (Phase 1 style cache hit). */
const PHASE1_CACHE_HIT_INFO: RewriteInfo = {
  original_query: "Python 怎么使用",
  rewritten_queries: [
    { query: "Python 怎么使用", strategy: null },
  ] as RewrittenQuery[],
  strategies_used: [],
  rewrite_time_ms: 2.1,
  cache_hit: true,
  // cache_level intentionally omitted (Phase 1 backward compat)
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

  // ── Phase 2: 策略标签颜色区分 ─────────────────────────────────────────

  describe("strategy tag color differentiation (Phase 2)", () => {
    it("normalize strategy has blue color classes", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: PHASE2_REWRITE_INFO },
      })

      await wrapper.find('[data-testid="rewrite-toggle"]').trigger("click")

      const tags = wrapper.findAll('[data-testid="strategy-tag"]')
      // First rewritten query uses "normalize" strategy
      const normalizeTag = tags[0]!
      expect(normalizeTag.text()).toContain("规范重述")
      expect(normalizeTag.classes()).toContain("bg-blue-100")
      expect(normalizeTag.classes()).toContain("text-blue-700")
    })

    it("term_align strategy has purple color classes", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: PHASE2_REWRITE_INFO },
      })

      await wrapper.find('[data-testid="rewrite-toggle"]').trigger("click")

      const tags = wrapper.findAll('[data-testid="strategy-tag"]')
      // Second rewritten query uses "term_align" strategy
      const termAlignTag = tags[1]!
      expect(termAlignTag.text()).toContain("术语对齐")
      expect(termAlignTag.classes()).toContain("bg-purple-100")
      expect(termAlignTag.classes()).toContain("text-purple-700")
    })

    it("expand strategy has amber color classes", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: PHASE2_REWRITE_INFO },
      })

      await wrapper.find('[data-testid="rewrite-toggle"]').trigger("click")

      const tags = wrapper.findAll('[data-testid="strategy-tag"]')
      // Third rewritten query uses "expand" strategy
      const expandTag = tags[2]!
      expect(expandTag.text()).toContain("扩展重述")
      expect(expandTag.classes()).toContain("bg-amber-100")
      expect(expandTag.classes()).toContain("text-amber-700")
    })

    it("context_fusion strategy has teal color classes", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: CONTEXT_FUSION_ONLY_INFO },
      })

      await wrapper.find('[data-testid="rewrite-toggle"]').trigger("click")

      const tag = wrapper.find('[data-testid="strategy-tag"]')
      expect(tag.text()).toContain("上下文融合")
      expect(tag.classes()).toContain("bg-teal-100")
      expect(tag.classes()).toContain("text-teal-700")
    })

    it("unknown strategy falls back to brand color classes", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: UNKNOWN_STRATEGY_INFO },
      })

      await wrapper.find('[data-testid="rewrite-toggle"]').trigger("click")

      const tag = wrapper.find('[data-testid="strategy-tag"]')
      expect(tag.classes()).toContain("bg-brand-100")
      expect(tag.classes()).toContain("text-brand-700")
    })
  })

  // ── Phase 2: 意图分类展示 ─────────────────────────────────────────────

  describe("intent classification display (Phase 2)", () => {
    it("shows intent badge in the toggle row when intent is provided", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: PHASE2_REWRITE_INFO },
      })

      // Intent badge should be visible in the toggle row (always visible, not just expanded)
      const intentBadge = wrapper.find('[data-testid="intent-badge"]')
      expect(intentBadge.exists()).toBe(true)
    })

    it("intent badge displays emoji and Chinese intent name", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: PHASE2_REWRITE_INFO },
      })

      const intentBadge = wrapper.find('[data-testid="intent-badge"]')
      // analytical → "分析型" with appropriate emoji
      expect(intentBadge.text()).toContain("分析型")
      // Should contain an emoji (at least one non-ASCII character)
      expect(intentBadge.text()).toMatch(/\P{ASCII}/u)
    })

    it("intent badge displays complexity score", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: PHASE2_REWRITE_INFO },
      })

      const intentBadge = wrapper.find('[data-testid="intent-badge"]')
      // Format: "{emoji} {中文名} · 复杂度 7"
      expect(intentBadge.text()).toContain("复杂度")
      expect(intentBadge.text()).toContain("7")
    })

    it("intent badge has text-xs style", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: PHASE2_REWRITE_INFO },
      })

      const intentBadge = wrapper.find('[data-testid="intent-badge"]')
      expect(intentBadge.classes()).toContain("text-xs")
    })

    it("factual intent shows correct Chinese label", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: FACTUAL_INTENT_INFO },
      })

      const intentBadge = wrapper.find('[data-testid="intent-badge"]')
      expect(intentBadge.text()).toContain("事实型")
      expect(intentBadge.text()).toContain("1")
    })

    it("no intent badge when intent is not provided (backward compat)", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: NO_INTENT_INFO },
      })

      const intentBadge = wrapper.find('[data-testid="intent-badge"]')
      expect(intentBadge.exists()).toBe(false)
    })
  })

  // ── Phase 2: 缓存层级展示 ─────────────────────────────────────────────

  describe("cache level display (Phase 2)", () => {
    it("shows L1 exact hit label when cache_level is L1", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: L1_CACHE_LEVEL_INFO },
      })

      await wrapper.find('[data-testid="rewrite-toggle"]').trigger("click")

      const cacheLevelTag = wrapper.find('[data-testid="cache-level-tag"]')
      expect(cacheLevelTag.exists()).toBe(true)
      expect(cacheLevelTag.text()).toContain("L1 精确命中")
    })

    it("shows L2 semantic hit label when cache_level is L2", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: L2_CACHE_LEVEL_INFO },
      })

      await wrapper.find('[data-testid="rewrite-toggle"]').trigger("click")

      const cacheLevelTag = wrapper.find('[data-testid="cache-level-tag"]')
      expect(cacheLevelTag.exists()).toBe(true)
      expect(cacheLevelTag.text()).toContain("L2 语义命中")
    })

    it("does not show cache level tag when cache_level is null", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: PHASE2_REWRITE_INFO },
      })

      await wrapper.find('[data-testid="rewrite-toggle"]').trigger("click")

      const cacheLevelTag = wrapper.find('[data-testid="cache-level-tag"]')
      expect(cacheLevelTag.exists()).toBe(false)
    })

    it("does not show cache level tag when cache_level is not provided (Phase 1 compat)", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: PHASE1_CACHE_HIT_INFO },
      })

      await wrapper.find('[data-testid="rewrite-toggle"]').trigger("click")

      const cacheLevelTag = wrapper.find('[data-testid="cache-level-tag"]')
      expect(cacheLevelTag.exists()).toBe(false)
    })
  })
})
