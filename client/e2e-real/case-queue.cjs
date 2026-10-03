// Real local HTTPS service + built React UI. The native bridge is modeled by
// scripts/acceptance_environment.py; this does not certify native deployment.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const metadata = path.join(process.env.LOCALAPPDATA, 'ClinicReporterAcceptance', 'case-queue-v1', 'current.json');
  const { url } = JSON.parse(fs.readFileSync(metadata, 'utf8'));
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const errors = [];
  try {
    const home = await browser.newPage();
    const admin = await browser.newPage({ viewport: { width: 1080, height: 760 } });
    const doctor = await browser.newPage({ viewport: { width: 720, height: 760 } });
    for (const page of [home, admin, doctor]) page.on('pageerror', error => errors.push(error.message));
    await home.goto(url);
    async function connect(page, profile) {
      await page.goto(url + 'app?profile=' + profile);
      await page.getByLabel('操作身分', { exact: true }).fill('SYN-DR-A');
      await page.getByRole('button', { name: '連線', exact: true }).click();
    }
    await connect(admin, 'admin');
    await admin.getByRole('button', { name: '案件工作清單', exact: true }).click();
    await connect(doctor, 'doctor');
    await doctor.getByText('符合條件 3 案 · 跨日未完成 1 案（優先顯示）', { exact: true }).waitFor();
    assert.ok((await doctor.getByRole('row').nth(1).innerText()).includes('SYN-0002'));
    assert.equal(await doctor.getByRole('button', { name: '刷新合成來源' }).count(), 0);
    await doctor.getByLabel('醫師篩選').selectOption('SYN-DR-B');
    await doctor.getByRole('button', { name: '查詢清單' }).click();
    await doctor.getByText('符合條件 1 案 · 跨日未完成 0 案（優先顯示）', { exact: true }).waitFor();
    await doctor.getByLabel('完整病歷號').fill('SYN-0001');
    await doctor.getByRole('button', { name: '查詢清單' }).click();
    await doctor.getByText('符合條件 2 案 · 跨日未完成 0 案（優先顯示）', { exact: true }).waitFor();
    assert.equal(await doctor.getByRole('heading', { name: '核對案件' }).count(), 0);
    await doctor.getByRole('button', { name: '核對此案' }).first().click();
    await doctor.getByRole('heading', { name: '核對案件' }).waitFor();
    assert.equal(await doctor.getByRole('heading', { name: '核對案件' }).evaluate(el => el === document.activeElement), true);
    await doctor.getByText('來源量 10 顆；回報量 10 顆', { exact: true }).waitFor();
    assert.equal(await doctor.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    fs.mkdirSync(path.join(__dirname, '../../screenshots'), { recursive: true });
    await doctor.screenshot({ path: path.join(__dirname, '../../screenshots/case-detail-720.png'), fullPage: true });
    await admin.getByLabel('醫師篩選').selectOption('');
    await admin.getByRole('button', { name: '查詢清單' }).click();
    await admin.getByText('符合條件 4 案 · 跨日未完成 1 案（優先顯示）', { exact: true }).waitFor();
    await admin.getByRole('button', { name: '刷新合成來源' }).click();
    await admin.getByText('合成來源刷新完成：新增 0 案，未變 4 案。', { exact: true }).waitFor();
    await admin.screenshot({ path: path.join(__dirname, '../../screenshots/case-queue-1080.png'), fullPage: true });
    await home.getByRole('button', { name: '停止測試中央', exact: true }).click();
    await doctor.getByRole('button', { name: '連線', exact: true }).waitFor({ timeout: 15000 });
    assert.equal(await doctor.getByText('合成病人甲', { exact: true }).count(), 0);
    assert.equal(await doctor.getByRole('heading', { name: '核對案件' }).count(), 0);
    assert.ok((await doctor.locator('main').innerText()).includes('紙本'));
    assert.equal(await doctor.evaluate(() => localStorage.length + sessionStorage.length), 0);
    await home.getByRole('button', { name: '啟動測試中央', exact: true }).click();
    await home.getByText('測試中央：運作中', { exact: true }).waitFor();
    await doctor.getByRole('button', { name: '連線', exact: true }).click();
    await doctor.getByText('符合條件 3 案 · 跨日未完成 1 案（優先顯示）', { exact: true }).waitFor();
    assert.deepEqual(errors, []);
    console.log('PASS: real HTTPS queue/filter/exact cross-physician search/detail/focus/dedup/outage/restart; no patient persistence or browser errors.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
