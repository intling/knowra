import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import type { QualityScores, RewriteInfo, RewrittenQuery } from "../../api/search"

// ── 测试 Fixture ──────────────────────────────────────────────────────────

/** 包含 rewritten_queries 的完整 RewriteInfo 数据 */
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

/** 缓存命中的 RewriteInfo（无 LLM 调用） */
const CACHE_HIT_REWRITE_INFO: RewriteInfo = {
  original_query: "Python 怎么使用",
  rewritten_queries: [
    { query: "Python 怎么使用", strategy: null },
  ] as RewrittenQuery[],
  strategies_used: [],
  rewrite_time_ms: 2.1,
  cache_hit: true,
}

/** rewritten_queries 为空的 RewriteInfo */
const EMPTY_QUERIES_REWRITE_INFO: RewriteInfo = {
  original_query: "简单查询",
  rewritten_queries: [] as RewrittenQuery[],
  strategies_used: [],
  rewrite_time_ms: 0.0,
  cache_hit: true,
}

/** 包含重写错误的 RewriteInfo */
const ERROR_REWRITE_INFO: RewriteInfo = {
  original_query: "失败查询",
  rewritten_queries: [] as RewrittenQuery[],
  strategies_used: [],
  rewrite_time_ms: 0.0,
  cache_hit: false,
  error: "Query rewriter timeout",
}

// ── Phase 2 Fixture ──────────────────────────────────────────────────────

/** 包含意图、复杂度和多种策略类型的 RewriteInfo */
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

/** 用于 teal 颜色验证的 context_fusion 策略 RewriteInfo */
const CONTEXT_FUSION_ONLY_INFO: RewriteInfo = {
  original_query: "它怎么用",
  rewritten_queries: [
    { query: "Python 怎么使用", strategy: "context_fusion" },
  ] as RewrittenQuery[],
  strategies_used: ["context_fusion"],
  rewrite_time_ms: 200.0,
  cache_hit: false,
}

/** L1 缓存层级的 RewriteInfo */
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

/** L2 缓存层级的 RewriteInfo */
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

/** 用于回退颜色验证的未知策略 RewriteInfo */
const UNKNOWN_STRATEGY_INFO: RewriteInfo = {
  original_query: "某个查询",
  rewritten_queries: [
    { query: "某个查询（未知策略处理）", strategy: "some_future_strategy" },
  ] as RewrittenQuery[],
  strategies_used: ["some_future_strategy"],
  rewrite_time_ms: 100.0,
  cache_hit: false,
}

/** 事实型意图、低复杂度的 RewriteInfo */
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

/** 无意图/复杂度的 RewriteInfo（向后兼容） */
const NO_INTENT_INFO: RewriteInfo = {
  original_query: "老数据",
  rewritten_queries: [
    { query: "老数据", strategy: "context_fusion" },
  ] as RewrittenQuery[],
  strategies_used: ["context_fusion"],
  rewrite_time_ms: 100.0,
  cache_hit: false,
  // 有意省略 intent 和 complexity
}

/** 缺少 cache_level 的 RewriteInfo（Phase 1 风格缓存命中） */
const PHASE1_CACHE_HIT_INFO: RewriteInfo = {
  original_query: "Python 怎么使用",
  rewritten_queries: [
    { query: "Python 怎么使用", strategy: null },
  ] as RewrittenQuery[],
  strategies_used: [],
  rewrite_time_ms: 2.1,
  cache_hit: true,
  // 有意省略 cache_level（Phase 1 向后兼容）
}

// ── Integration Fixture（质量评分、回溯）──────────────────────────────────

/** 优秀质量评分的 RewriteInfo */
const EXCELLENT_QUALITY_INFO: RewriteInfo = {
  original_query: "数据库咋优化",
  rewritten_queries: [
    {
      query: "如何优化数据库性能",
      strategy: "normalize",
      duration_ms: 120.5,
      tokens: 45,
    },
  ] as RewrittenQuery[],
  strategies_used: ["normalize"],
  rewrite_time_ms: 320.5,
  cache_hit: false,
  intent: "analytical",
  complexity: 7,
  quality_scores: {
    semantic_preservation: 5,
    clarity_improvement: 5,
    information_gain: 4,
    term_accuracy: 5,
    retrievability: 5,
    total_score: 24,
    verdict: "excellent",
    issues: [],
  } as QualityScores,
  backtrack_triggered: false,
  backtrack_strategy: null,
}

/** 良好质量评分的 RewriteInfo */
const GOOD_QUALITY_INFO: RewriteInfo = {
  original_query: "Python咋学",
  rewritten_queries: [
    {
      query: "如何系统地学习 Python 编程",
      strategy: "normalize",
      duration_ms: 95.0,
      tokens: 38,
    },
  ] as RewrittenQuery[],
  strategies_used: ["normalize"],
  rewrite_time_ms: 250.0,
  cache_hit: false,
  quality_scores: {
    semantic_preservation: 4,
    clarity_improvement: 4,
    information_gain: 3,
    term_accuracy: 4,
    retrievability: 3,
    total_score: 18,
    verdict: "good",
    issues: ["可进一步扩展关键词覆盖"],
  } as QualityScores,
  backtrack_triggered: false,
}

/** 一般质量评分的 RewriteInfo */
const MARGINAL_QUALITY_INFO: RewriteInfo = {
  original_query: "那个东西怎么弄",
  rewritten_queries: [
    {
      query: "那个东西怎么弄",
      strategy: "normalize",
      duration_ms: 80.0,
      tokens: 15,
    },
  ] as RewrittenQuery[],
  strategies_used: ["normalize"],
  rewrite_time_ms: 200.0,
  cache_hit: false,
  quality_scores: {
    semantic_preservation: 3,
    clarity_improvement: 2,
    information_gain: 1,
    term_accuracy: 3,
    retrievability: 2,
    total_score: 11,
    verdict: "marginal",
    issues: ["语义保留度低", "信息增益不足"],
  } as QualityScores,
  backtrack_triggered: false,
}

/** 较差质量评分的 RewriteInfo */
const POOR_QUALITY_INFO: RewriteInfo = {
  original_query: "??",
  rewritten_queries: [
    {
      query: "??",
      strategy: "normalize",
      duration_ms: 50.0,
      tokens: 5,
    },
  ] as RewrittenQuery[],
  strategies_used: ["normalize"],
  rewrite_time_ms: 150.0,
  cache_hit: false,
  quality_scores: {
    semantic_preservation: 1,
    clarity_improvement: 1,
    information_gain: 1,
    term_accuracy: 1,
    retrievability: 1,
    total_score: 5,
    verdict: "poor",
    issues: ["无法理解查询意图", "改写无改善"],
  } as QualityScores,
  backtrack_triggered: false,
}

/** 触发回溯的 RewriteInfo */
const BACKTRACK_INFO: RewriteInfo = {
  original_query: "数据库咋优化",
  rewritten_queries: [
    {
      query: "数据库性能优化：索引策略、查询优化、缓存配置、连接池管理",
      strategy: "expand",
      duration_ms: 210.0,
      tokens: 65,
    },
  ] as RewrittenQuery[],
  strategies_used: ["normalize", "expand"],
  rewrite_time_ms: 520.0,
  cache_hit: false,
  intent: "analytical",
  complexity: 7,
  quality_scores: {
    semantic_preservation: 4,
    clarity_improvement: 4,
    information_gain: 5,
    term_accuracy: 4,
    retrievability: 4,
    total_score: 21,
    verdict: "good",
    issues: [],
  } as QualityScores,
  backtrack_triggered: true,
  backtrack_strategy: "expand",
}

/** 无 quality_scores 的 RewriteInfo（向后兼容 / null 处理） */
const NO_QUALITY_SCORES_INFO: RewriteInfo = {
  original_query: "老数据查询",
  rewritten_queries: [
    { query: "老数据查询", strategy: "context_fusion" },
  ] as RewrittenQuery[],
  strategies_used: ["context_fusion"],
  rewrite_time_ms: 100.0,
  cache_hit: false,
  // 有意省略 quality_scores（Phase 2 向后兼容）
  // 有意省略 backtrack_triggered
}

// ── 懒加载导入（组件可能尚未创建 — TDD 红测试）──

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

  // ── Integration: 质量评分颜色区分 ───────────────────────────────────

  describe("quality score color differentiation (Integration)", () => {
    it("excellent verdict uses emerald-600 text color", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: EXCELLENT_QUALITY_INFO },
      })

      await wrapper.find('[data-testid="rewrite-toggle"]').trigger("click")

      const scoreContainer = wrapper.find('[data-testid="quality-score-container"]')
      expect(scoreContainer.exists()).toBe(true)

      const verdictEl = scoreContainer.find('[data-testid="quality-verdict"]')
      expect(verdictEl.exists()).toBe(true)
      expect(verdictEl.text()).toContain("优秀")
      expect(verdictEl.classes()).toContain("text-emerald-600")
    })

    it("good verdict uses amber-600 text color", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: GOOD_QUALITY_INFO },
      })

      await wrapper.find('[data-testid="rewrite-toggle"]').trigger("click")

      const verdictEl = wrapper.find('[data-testid="quality-verdict"]')
      expect(verdictEl.exists()).toBe(true)
      expect(verdictEl.text()).toContain("良好")
      expect(verdictEl.classes()).toContain("text-amber-600")
    })

    it("marginal verdict uses red-600 text color", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: MARGINAL_QUALITY_INFO },
      })

      await wrapper.find('[data-testid="rewrite-toggle"]').trigger("click")

      const verdictEl = wrapper.find('[data-testid="quality-verdict"]')
      expect(verdictEl.exists()).toBe(true)
      expect(verdictEl.text()).toContain("一般")
      expect(verdictEl.classes()).toContain("text-red-600")
    })

    it("poor verdict uses red-600 text color", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: POOR_QUALITY_INFO },
      })

      await wrapper.find('[data-testid="rewrite-toggle"]').trigger("click")

      const verdictEl = wrapper.find('[data-testid="quality-verdict"]')
      expect(verdictEl.exists()).toBe(true)
      expect(verdictEl.text()).toContain("较差")
      expect(verdictEl.classes()).toContain("text-red-600")
    })

    it("total score number uses font-mono tabular-nums for monospaced digit rendering", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: EXCELLENT_QUALITY_INFO },
      })

      await wrapper.find('[data-testid="rewrite-toggle"]').trigger("click")

      const totalScoreEl = wrapper.find('[data-testid="quality-total-score"]')
      expect(totalScoreEl.exists()).toBe(true)
      expect(totalScoreEl.text()).toContain("24")
      expect(totalScoreEl.classes()).toContain("font-mono")
      expect(totalScoreEl.classes()).toContain("tabular-nums")
    })
  })

  // ── Integration: 5 维度评分条形图展开/收起 ───────────────────────────

  describe("5-dimension score bar chart expand/collapse (Integration)", () => {
    it("dimension details are hidden by default", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: EXCELLENT_QUALITY_INFO },
      })

      await wrapper.find('[data-testid="rewrite-toggle"]').trigger("click")

      // Quality score container should be visible
      expect(wrapper.find('[data-testid="quality-score-container"]').exists()).toBe(true)
      // But dimension details should NOT be visible initially
      expect(wrapper.find('[data-testid="quality-dimensions"]').exists()).toBe(false)
    })

    it("clicking dimension toggle expands the 5-dimension bar chart", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: EXCELLENT_QUALITY_INFO },
      })

      await wrapper.find('[data-testid="rewrite-toggle"]').trigger("click")

      // Toggle exists
      const toggleBtn = wrapper.find('[data-testid="quality-dimensions-toggle"]')
      expect(toggleBtn.exists()).toBe(true)

      // Click to expand
      await toggleBtn.trigger("click")

      // Dimension details should now be visible
      const dimensionsEl = wrapper.find('[data-testid="quality-dimensions"]')
      expect(dimensionsEl.exists()).toBe(true)
    })

    it("clicking dimension toggle again collapses the bar chart", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: EXCELLENT_QUALITY_INFO },
      })

      await wrapper.find('[data-testid="rewrite-toggle"]').trigger("click")

      const toggleBtn = wrapper.find('[data-testid="quality-dimensions-toggle"]')

      // Expand first
      await toggleBtn.trigger("click")
      expect(wrapper.find('[data-testid="quality-dimensions"]').exists()).toBe(true)

      // Collapse
      await toggleBtn.trigger("click")
      expect(wrapper.find('[data-testid="quality-dimensions"]').exists()).toBe(false)
    })

    it("displays all 5 dimensions with label and score", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: EXCELLENT_QUALITY_INFO },
      })

      await wrapper.find('[data-testid="rewrite-toggle"]').trigger("click")
      await wrapper.find('[data-testid="quality-dimensions-toggle"]').trigger("click")

      const dimensionItems = wrapper.findAll('[data-testid="quality-dimension-item"]')
      expect(dimensionItems).toHaveLength(5)

      // Each dimension should have a label and a score
      for (const item of dimensionItems) {
        const label = item.find('[data-testid="quality-dimension-label"]')
        expect(label.exists()).toBe(true)
        expect(label.text().length).toBeGreaterThan(0)

        const score = item.find('[data-testid="quality-dimension-score"]')
        expect(score.exists()).toBe(true)
        // Score should be a number between 1 and 5
        const scoreText = score.text()
        expect(scoreText).toMatch(/[1-5]/)
      }
    })

    it("each dimension has a bar visualization with bg-neutral-200 track and colored fill", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: EXCELLENT_QUALITY_INFO },
      })

      await wrapper.find('[data-testid="rewrite-toggle"]').trigger("click")
      await wrapper.find('[data-testid="quality-dimensions-toggle"]').trigger("click")

      const dimensionItems = wrapper.findAll('[data-testid="quality-dimension-item"]')

      for (const item of dimensionItems) {
        // Bar background track
        const barBg = item.find('[data-testid="quality-dimension-bar-bg"]')
        expect(barBg.exists()).toBe(true)
        expect(barBg.classes()).toContain("bg-neutral-200")
        expect(barBg.classes()).toContain("rounded-full")
        expect(barBg.classes()).toContain("h-1.5")

        // Bar colored fill
        const barFill = item.find('[data-testid="quality-dimension-bar-fill"]')
        expect(barFill.exists()).toBe(true)
        expect(barFill.classes()).toContain("rounded-full")
        expect(barFill.classes()).toContain("h-1.5")
      }
    })
  })

  // ── Integration: 回溯提示展示 ───────────────────────────────────────

  describe("backtrack notice display (Integration)", () => {
    it("shows backtrack notice when backtrack_triggered is true", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: BACKTRACK_INFO },
      })

      await wrapper.find('[data-testid="rewrite-toggle"]').trigger("click")

      const backtrackNotice = wrapper.find('[data-testid="backtrack-notice"]')
      expect(backtrackNotice.exists()).toBe(true)
      expect(backtrackNotice.text()).toContain("已自动升级策略重新改写")
    })

    it("backtrack notice uses text-xs text-amber-500 styling", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: BACKTRACK_INFO },
      })

      await wrapper.find('[data-testid="rewrite-toggle"]').trigger("click")

      const backtrackNotice = wrapper.find('[data-testid="backtrack-notice"]')
      expect(backtrackNotice.classes()).toContain("text-xs")
      expect(backtrackNotice.classes()).toContain("text-amber-500")
    })

    it("does not show backtrack notice when backtrack_triggered is false", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: EXCELLENT_QUALITY_INFO },
      })

      await wrapper.find('[data-testid="rewrite-toggle"]').trigger("click")

      const backtrackNotice = wrapper.find('[data-testid="backtrack-notice"]')
      expect(backtrackNotice.exists()).toBe(false)
    })
  })

  // ── Integration: 评分缺失时容错 ─────────────────────────────────────

  describe("graceful handling when quality_scores is missing (Integration)", () => {
    it("does not render quality score section when quality_scores is null", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: NO_QUALITY_SCORES_INFO },
      })

      await wrapper.find('[data-testid="rewrite-toggle"]').trigger("click")

      // Quality score container should not exist
      const scoreContainer = wrapper.find('[data-testid="quality-score-container"]')
      expect(scoreContainer.exists()).toBe(false)

      // Quality dimensions toggle should not exist
      const dimensionsToggle = wrapper.find('[data-testid="quality-dimensions-toggle"]')
      expect(dimensionsToggle.exists()).toBe(false)
    })

    it("component does not crash when quality_scores is not provided", async () => {
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: NO_QUALITY_SCORES_INFO },
      })

      await wrapper.find('[data-testid="rewrite-toggle"]').trigger("click")

      // All other content should still render normally
      expect(wrapper.find('[data-testid="rewrite-content"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="original-query"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="rewritten-query-item"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="rewrite-time"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="cache-hit"]').exists()).toBe(true)
    })

    it("does not render quality score section when quality_scores is null even for Phase 2 data", async () => {
      // FULL_REWRITE_INFO from Phase 1 has no quality_scores field
      const RewritePanel = await getRewritePanel()
      const wrapper = mount(RewritePanel, {
        props: { rewriteInfo: FULL_REWRITE_INFO },
      })

      await wrapper.find('[data-testid="rewrite-toggle"]').trigger("click")

      const scoreContainer = wrapper.find('[data-testid="quality-score-container"]')
      expect(scoreContainer.exists()).toBe(false)

      // Other Phase 1 content should still render
      expect(wrapper.find('[data-testid="rewritten-queries-list"]').exists()).toBe(true)
    })
  })
})
