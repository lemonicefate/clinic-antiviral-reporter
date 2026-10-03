const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const { url } = JSON.parse(fs.readFileSync(path.join(process.env.LOCALAPPDATA,
    'ClinicReporterAcceptance/case-queue-v1/current.json'), 'utf8'));
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const first = await browser.newPage({ viewport: { width: 1080, height: 900 } });
    const second = await browser.newPage({ viewport: { width: 720, height: 900 } });
    const errors = [];
    for (const page of [first, second]) page.on('pageerror', e => errors.push(e.message));
    async function openCase(page) {
      await page.goto(url + 'app?profile=doctor');
      await page.getByLabel('操作身分', { exact: true }).fill('SYN-DR-A');
      await page.getByRole('button', { name: '連線', exact: true }).click();
      await page.getByRole('row').filter({ hasText: 'SYN-ORDER-1' }).getByRole('button', { name: '核對此案' }).click();
      await page.getByLabel('官方用藥對象', { exact: true }).waitFor();
      await page.waitForFunction(() => document.querySelector('select[required]')?.options.length === 38);
    }
    await openCase(first);
    await openCase(second);
    const options = await first.getByLabel('官方用藥對象', { exact: true }).locator('option').evaluateAll(
      nodes => nodes.map(n => n.value).filter(Boolean));
    assert.equal(options.length, 37);
    await first.getByLabel('官方用藥對象', { exact: true }).selectOption(options[0]);
    assert.equal(await first.getByRole('button', { name: '儲存用藥理由' }).isDisabled(), true);
    await first.getByRole('checkbox').check();
    await first.getByRole('button', { name: '儲存用藥理由' }).focus();
    await first.keyboard.press('Enter');
    await first.getByText('用藥理由已儲存，清單已更新。', { exact: true }).waitFor();
    await first.getByText('待填理由 2 案；已填理由仍須完成回報核對。', { exact: true }).waitFor();
    await second.getByLabel('官方用藥對象', { exact: true }).selectOption(options[1]);
    await second.getByRole('checkbox').check();
    await second.getByRole('button', { name: '儲存用藥理由' }).click();
    await second.getByRole('heading', { name: '理由已被其他操作更新' }).waitFor();
    assert.ok((await second.getByRole('alert').innerText()).includes(options[0]));
    assert.ok((await second.getByRole('alert').innerText()).includes(options[1]));
    assert.equal(await second.getByRole('button', { name: '儲存用藥理由' }).isDisabled(), true);
    assert.equal(await second.getByRole('checkbox').isChecked(), false);
    assert.equal(await second.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    fs.mkdirSync(path.join(__dirname, '../../screenshots'), { recursive: true });
    await second.screenshot({ path: path.join(__dirname, '../../screenshots/reason-conflict-720.png'), fullPage: true });
    await second.getByRole('button', { name: '重新讀取並核對' }).click();
    await second.getByText('目前理由：' + options[0], { exact: true }).waitFor();
    assert.equal(await second.getByRole('checkbox').isChecked(), false);
    await second.getByLabel('官方用藥對象', { exact: true }).selectOption(options[1]);
    await second.getByRole('checkbox').check();
    await second.getByRole('button', { name: '儲存用藥理由' }).click();
    await second.getByText('用藥理由已儲存，清單已更新。', { exact: true }).waitFor();
    await second.getByRole('row').filter({ hasText: 'SYN-ORDER-1' }).getByRole('button', { name: '核對此案' }).click();
    await second.getByText('目前理由：' + options[1], { exact: true }).waitFor();
    await second.getByLabel('官方用藥對象', { exact: true }).selectOption(options[2]);
    await second.evaluate(() => window.dispatchEvent(new Event('offline')));
    await second.getByRole('button', { name: '連線', exact: true }).waitFor();
    assert.equal(await second.getByLabel('官方用藥對象', { exact: true }).count(), 0);
    assert.equal(await second.evaluate(() => localStorage.length + sessionStorage.length), 0);
    // A saved mutation followed by a failed list read must not claim refresh success.
    await first.getByRole('row').filter({ hasText: 'SYN-ORDER-1' }).getByRole('button', { name: '核對此案' }).click();
    await first.getByLabel('官方用藥對象', { exact: true }).selectOption(options[2]);
    await first.getByRole('checkbox').check();
    let failedRefresh = false;
    await first.route('**/invoke', async route => {
      const data = route.request().postDataJSON();
      if (!failedRefresh && data.command === 'central_request' && data.args?.request?.path.startsWith('/api/v1/cases?')) {
        failedRefresh = true;
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 400, body: '{}' }) });
      } else await route.continue();
    });
    await first.getByRole('button', { name: '儲存用藥理由' }).click();
    await first.getByText('用藥理由已儲存；清單讀取失敗，請重新查詢。', { exact: true }).waitFor();
    assert.equal(await first.getByText('用藥理由已儲存，清單已更新。', { exact: true }).count(), 0);
    await first.unroute('**/invoke');
    await first.getByRole('button', { name: '查詢清單' }).click();
    await first.getByText('待填理由 2 案；已填理由仍須完成回報核對。', { exact: true }).waitFor();
    assert.deepEqual(errors, []);
    console.log('PASS: 37 exact official options, patient confirmation, keyboard save, counts, two-client conflict/re-review, offline form clearing, and honest post-save list failure.');
  } finally { await browser.close(); }
})().catch(e => { console.error(e.message); process.exitCode = 1; });
