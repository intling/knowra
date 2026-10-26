/* 本地验收：拦截 API 提供确定性响应，仅验证真实 UI，不调用线上账号或模型。 */
const { chromium } = require(process.env.ADAPTIVE_PLAYWRIGHT_PATH || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.ADAPTIVE_BROWSER_BASE_URL || 'http://127.0.0.1:5176';
const report = { checks: [], screenshots: [], errors: [], mocked: true };

(async () => {
  const fixtures = await import('../../polish-frontend-ui/browser/fixtures.mjs');
  const general = { ...fixtures.searchResponse, answer_mode: 'general', retrieval_status: 'no_match',
    answer: '装饰器可以包装函数并扩展行为。', results: [], summary_coverage: null,
    query_embedding_preview: [], total_searched: 0, searched_document_count: 0 };
  const results = [0, 1, 2].map((i) => ({ ...fixtures.searchResponse.results[i],
    parsed_document_id: `00000000-0000-4000-8000-00000000000${i}`,
    document_name: ['数据结构.md', '异常处理.md', '虚拟环境.md'][i],
    text: ['列表可变、元组不可变。', 'finally 用于可靠清理。', '独立环境隔离依赖。'][i] }));
  const scenarios = [
    ['general', 'Python 装饰器怎么使用？', general],
    ['clarification', '根据我的资料，预算是多少？', { ...general, answer_mode: 'clarification',
      answer: '请上传或选择相关资料后再试。', answer_tokens: null, chat_model: null }],
    ['summary', '总结这些资料的核心观点', { ...general, answer_mode: 'summary', retrieval_status: 'matched',
      answer: '核心观点：列表可变、finally 可靠清理、独立环境隔离依赖。', results,
      summary_coverage: { document_count: 3, included_document_count: 3, total_chunks: 3, included_chunks: 3, truncated: false } }],
    ['partial', '概览这些资料', { ...general, answer_mode: 'summary', retrieval_status: 'matched',
      answer: '以下基于部分资料总结：列表可变。', results: results.slice(0, 1),
      summary_coverage: { document_count: 3, included_document_count: 1, total_chunks: 100, included_chunks: 8, truncated: true } }],
    ['unavailable', '解释一下闭包', { ...general, retrieval_status: 'unavailable' }],
    ['generation-error', '请再解释一下', { ...general, answer: 'AI 回答生成失败，请稍后重试。',
      generation_error: '受控模型超时', answer_tokens: null, chat_model: null }],
  ];
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
    page.on('pageerror', (error) => report.errors.push(error.message));
    await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
      const url = new URL(route.request().url());
      let body;
      if (url.pathname === '/api/users/me') body = { ...fixtures.user, role: 'member', permissions: ['knowledge:read', 'knowledge:write'] };
      else if (url.pathname === '/api/parsed-documents') body = fixtures.documents;
      else if (url.pathname === '/api/search') {
        const request = route.request().postDataJSON();
        const scenario = scenarios.find(([, query]) => query === request.query);
        assert(scenario, '未知的浏览器场景请求');
        body = { ...scenario[2], query: request.query };
      } else { await route.fulfill({ status: 404, json: { detail: '本地验收未配置此 API' } }); return; }
      await route.fulfill({ status: 200, json: body });
    });
    await page.goto(base);
    await page.getByTestId('welcome-view').waitFor();
    assert((await page.getByTestId('welcome-subtitle').innerText()).includes('直接提问'));
    report.checks.push('欢迎说明允许直接提问');
    for (const [name, query, response] of scenarios) {
      const input = page.getByTestId('chat-input');
      await input.fill(query); await input.press('Enter');
      const turn = page.locator('[data-turn-id]').last();
      if (name === 'generation-error') {
        await turn.getByTestId('answer-degraded').waitFor();
        assert(!(await turn.innerText()).includes('基于通用知识'));
      } else {
        await turn.getByTestId('answer-content').waitFor();
        assert((await turn.getByTestId('answer-content').innerText()).includes(response.answer));
      }
      if (['general', 'clarification', 'unavailable'].includes(name)) {
        assert.equal(await turn.getByTestId('source-list').count(), 0);
        assert.equal(await turn.getByTestId('citation-stats').count(), 0);
        assert.equal(await turn.getByTestId('retrieval-details').count(), 0);
      }
      if (name === 'general') {
        assert((await turn.innerText()).includes('基于通用知识'));
        assert.equal(await turn.getByTestId('copy-answer-button').count(), 1);
        assert.equal(await turn.getByTestId('token-total').count(), 1);
      }
      if (name === 'clarification') assert.equal(await turn.getByTestId('token-stats').count(), 0);
      if (name === 'summary' || name === 'partial') {
        assert.equal(await turn.getByTestId('source-item').count(), name === 'summary' ? 3 : 1);
        await turn.getByTestId('source-toggle').first().click();
        assert((await turn.getByTestId('source-chunk-text').first().innerText()).includes('列表可变'));
        assert(!(await turn.innerText()).includes('检索排名'));
        assert.equal(await turn.getByTestId('retrieval-details').count(), 0);
      }
      if (name === 'partial') {
        assert((await turn.innerText()).includes('基于部分资料总结'));
        assert((await turn.innerText()).includes('1 / 3'));
      }
      if (name === 'unavailable') assert((await turn.innerText()).includes('检索暂不可用'));
      await turn.scrollIntoViewIfNeeded();
      const screenshot = `${name}-desktop.png`;
      await page.screenshot({ path: path.join(__dirname, screenshot) });
      report.screenshots.push(screenshot); report.checks.push(name);
    }
    await page.setViewportSize({ width: 390, height: 844 });
    const dimensions = await page.evaluate(() => ({ width: innerWidth, actual: document.documentElement.scrollWidth }));
    assert(dimensions.actual <= dimensions.width);
    await page.screenshot({ path: path.join(__dirname, 'mobile.png') });
    report.screenshots.push('mobile.png'); report.checks.push('390px 无横向溢出');
    assert.deepEqual(report.errors, []);
  } finally {
    await browser.close();
    fs.writeFileSync(path.join(__dirname, 'browser-report.json'), JSON.stringify(report, null, 2) + '\n');
  }
})().catch((error) => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
