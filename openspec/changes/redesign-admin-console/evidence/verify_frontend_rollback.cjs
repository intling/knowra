/* Browser rollback rehearsal against the disposable local fixture database only. */
const { chromium } = require(process.env.ADMIN_PLAYWRIGHT_PATH || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const base = 'http://localhost:5173';
const dist = process.env.ADMIN_ROLLBACK_DIST || '/tmp/knowra-admin-verification/rollback/front/dist';
const report = { source: 'git archive b767b6bb5f309a60d55b6a1fdd8499fdf99b4633 front', checks: [] };
function snapshot() {
  const sql = `SELECT json_build_object(
    'revision',(SELECT version_num FROM alembic_version),
    'accounts',(SELECT json_agg(row_to_json(a) ORDER BY a.id) FROM (SELECT id,role,status,deleted_at FROM users) a),
    'quota',(SELECT COALESCE(json_agg(row_to_json(q) ORDER BY q.user_id),'[]'::json) FROM (SELECT * FROM user_chat_limits) q),
    'bindings',(SELECT json_agg(row_to_json(b) ORDER BY b.kind) FROM (SELECT * FROM model_bindings) b),
    'audit_ids',(SELECT COALESCE(json_agg(id ORDER BY id),'[]'::json) FROM admin_audit_events),
    'probe_ids',(SELECT COALESCE(json_agg(id ORDER BY id),'[]'::json) FROM model_probe_results),
    'upload_ownership',(SELECT md5(COALESCE(string_agg(id::text || ':' || owner_user_id::text, ',' ORDER BY id),'')) FROM uploaded_files),
    'vector_count',(SELECT count(*) FROM document_embeddings),
    'vector_type',(SELECT format_type(atttypid,atttypmod) FROM pg_attribute WHERE attrelid='document_embeddings'::regclass AND attname='embedding_vector')
  )`;
  return JSON.parse(execFileSync('docker', ['exec', 'knowra-admin-continue-verify', 'psql', '-U', 'knowra_verify', '-d', 'knowra_verify', '-Atc', sql], { encoding: 'utf8' }));
}
function record(check) { report.checks.push(check); console.log('PASS ' + check); }
(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const response = await context.request.post(base + '/api/auth/login', { data: { email: 'browser-admin@example.com', password: 'Browser-Verify-2026' } });
    assert.equal(response.status(), 200);
    const before = snapshot();
    report.before = before;
    await context.route(base + '/**', async route => {
      const pathname = new URL(route.request().url()).pathname;
      if (pathname.startsWith('/api/')) return route.continue();
      const relative = pathname.replace(/^\/+/, '');
      const target = path.resolve(dist, relative || 'index.html');
      assert(target.startsWith(path.resolve(dist) + path.sep));
      const asset = fs.existsSync(target) && fs.statSync(target).isFile() ? target : path.join(dist, 'index.html');
      const type = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' }[path.extname(asset)] || 'application/octet-stream';
      await route.fulfill({ status: 200, contentType: type, body: fs.readFileSync(asset) });
    });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base + '/admin');
    await page.waitForURL('**/admin/users');
    await page.getByRole('heading', { name: '用户管理', exact: true }).waitFor();
    await page.getByTestId('admin-user-row').first().waitFor();
    assert.equal(await page.getByTestId('admin-user-search').count(), 0, 'Must actually serve the previous bundle');
    record('previous production bundle opens original admin users route against new backend');
    const suffix = Date.now();
    await page.getByTestId('admin-create-user').click();
    const userForm = page.getByTestId('admin-create-form');
    await userForm.locator('[name=email]').fill('rollback-' + suffix + '@example.com');
    await userForm.locator('[name=display_name]').fill('回退演练账号');
    await userForm.locator('[name=password]').fill('Rollback-Verify-2026');
    await userForm.locator('[name=confirm_password]').fill('Rollback-Verify-2026');
    const [created] = await Promise.all([
      page.waitForResponse(r => r.url().endsWith('/api/admin/users') && r.request().method() === 'POST'),
      userForm.locator('[type=submit]').click(),
    ]);
    assert.equal(created.status(), 201);
    await page.getByRole('status').filter({ hasText: '用户已创建' }).waitFor();
    record('old user creation contract and successful audit remain compatible');
    await page.goto(base + '/admin/models');
    await page.getByRole('heading', { name: '模型配置', exact: true }).waitFor();
    await page.getByTestId('admin-create-model').click();
    const modelForm = page.getByTestId('admin-model-form');
    await modelForm.locator('[name=name]').fill('回退演练模型 ' + suffix);
    await modelForm.locator('[name=base_url]').fill('http://127.0.0.1:18082/v1');
    await modelForm.locator('[name=model]').fill('rollback-local');
    const [model] = await Promise.all([
      page.waitForResponse(r => r.url().endsWith('/api/admin/models') && r.request().method() === 'POST'),
      modelForm.locator('[type=submit]').click(),
    ]);
    assert.equal(model.status(), 201);
    await page.getByTestId('admin-model-row').filter({ hasText: '回退演练模型 ' + suffix }).waitFor();
    await page.screenshot({ path: path.join(__dirname, 'rollback-old-models-1440.png'), fullPage: true });
    record('old model list and creation contract accept additive revision response');
    const after = snapshot();
    report.after = after;
    assert.equal(after.revision, '20261022_0002');
    for (const account of before.accounts) {
      assert.deepEqual(after.accounts.find(item => item.id === account.id), account);
    }
    assert.equal(after.accounts.length, before.accounts.length + 1);
    assert.deepEqual(after.quota, before.quota);
    assert.deepEqual(after.bindings, before.bindings);
    assert.deepEqual(after.probe_ids, before.probe_ids);
    assert(before.audit_ids.every(id => after.audit_ids.includes(id)));
    assert.equal(after.audit_ids.length, before.audit_ids.length + 2);
    assert.equal(after.upload_ownership, before.upload_ownership);
    assert.equal(after.vector_count, before.vector_count);
    assert.equal(after.vector_type, 'vector(2560)');
    assert.deepEqual(errors, []);
    record('rollback preserves quotas, model bindings, every audit/probe record, ownership and vector(2560)');
    await context.close();
  } finally {
    await browser.close();
    fs.writeFileSync(path.join(__dirname, 'rollback-report.json'), JSON.stringify(report, null, 2));
  }
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
