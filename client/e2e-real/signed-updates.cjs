// Real WebView2/Tauri IPC and signed NSIS installers; synthetic credentials only.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const crypto = require('node:crypto');
const { spawn, execFileSync } = require('node:child_process');
const assert = require('node:assert/strict');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const owned = [];
const executable = path.join(config.installation, 'clinic-antiviral-reporter.exe');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, message) {
  for (let i = 0; i < 150; i++) { if (await check()) return; await pause(200); }
  throw new Error(message);
}
async function unusedPort() {
  const server = net.createServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}
const hash = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
function bundledHash(file) {
  // Tauri patches this documented marker to NSS in the installer payload, then
  // restores UNK in target/debug. Compare every byte against that exact transform.
  const bytes = fs.readFileSync(file);
  const marker = Buffer.from('__TAURI_BUNDLE_TYPE_VAR_UNK');
  const offset = bytes.indexOf(marker);
  assert.ok(offset >= 0 && bytes.indexOf(marker, offset + 1) === -1, 'Unique Tauri bundle marker missing');
  Buffer.from('__TAURI_BUNDLE_TYPE_VAR_NSS').copy(bytes, offset);
  return crypto.createHash('sha256').update(bytes).digest('hex');
}
async function installed(version) {
  await until(() => {
    try {
      const record = execFileSync('reg.exe', ['query', 'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\公費抗病毒藥劑回報', '/v', 'DisplayVersion'], { windowsHide: true }).toString();
      return record.includes(version) && hash(executable) === bundledHash(config.releases[version].executable);
    } catch { return false; }
  }, 'Installed version or exact executable bytes did not match ' + version);
  // Registry/files can become final before the detached NSIS process exits.
  // Query only process image paths below this run's owned cache before proceeding.
  await until(() => execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
    '$prefix = [IO.Path]::GetFullPath($env:CLINIC_TEST_UPDATE_CACHE).TrimEnd([char]92) + [char]92; ' +
    '$active = @(Get-Process -Name previous,next -ErrorAction SilentlyContinue | Where-Object { ' +
    '$_.Path -and $_.Path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) }); ' +
    'if ($active.Count -eq 0) { Write-Output done }'],
    { windowsHide: true, env: { ...process.env, CLINIC_TEST_UPDATE_CACHE: config.cache } }).toString().trim() === 'done',
    'Owned installer did not exit after writing its files');
}
async function launch(version) {
  const port = await unusedPort();
  const child = spawn(executable, [], { stdio: 'ignore', windowsHide: true,
    env: { ...process.env, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: '--remote-debugging-port=' + port } });
  owned.push(child);
  let browser;
  await until(async () => {
    if (child.exitCode !== null) throw new Error('Owned client exited before connection');
    try { browser = await chromium.connectOverCDP('http://127.0.0.1:' + port, { timeout: 500 }); return true; }
    catch { return false; }
  }, 'Owned WebView2 debugging endpoint did not start');
  let page;
  await until(() => {
    page = browser.contexts().flatMap(context => context.pages()).find(item => item.url().includes('tauri.localhost'));
    return !!page;
  }, 'Tauri page not found');
  await page.locator('.update-panel summary').waitFor();
  const invoke = (command, args) => page.evaluate(({ command, args }) => window.__TAURI_INTERNALS__.invoke(command, args), { command, args });
  assert.equal((await invoke('update_state')).currentVersion, version);
  return { child, page, invoke };
}
(async () => {
  try {
    await installed('0.1.0');
    let app = await launch('0.1.0');
    await app.page.getByLabel('裝置設定方式').selectOption('import');
    await app.page.getByLabel('中央服務位址').fill(config.endpoint);
    await app.page.getByLabel('操作身分', { exact: true }).fill('SYN-UPDATE');
    await app.page.getByLabel('初始裝置金鑰').fill(config.credential);
    await app.page.getByRole('button', { name: '連線', exact: true }).click();
    await app.page.getByRole('heading', { name: '裝置管理', exact: true }).waitFor();
    await app.page.locator('.update-panel summary').click();
    await app.page.getByRole('button', { name: '檢查更新', exact: true }).click();
    await app.page.getByText(/有新版本 0.1.1/).waitFor();
    await until(() => app.page.getByRole('button', { name: '檢查更新', exact: true }).isEnabled(), 'Update check did not settle');
    fs.writeFileSync(config.scenario, JSON.stringify({ mode: 'truncate' }));
    await assert.rejects(() => app.invoke('prepare_update', { expectedVersion: '0.1.1' }), error => String(error).includes('不完整'));
    assert.equal(app.child.exitCode, null);
    assert.equal((await app.invoke('update_state')).planToken, null);
    fs.writeFileSync(config.scenario, JSON.stringify({ mode: 'disconnect' }));
    await assert.rejects(() => app.invoke('prepare_update', { expectedVersion: '0.1.1' }), error => String(error).includes('中斷'));
    assert.equal(app.child.exitCode, null);
    assert.equal((await app.invoke('update_state')).planToken, null);
    fs.writeFileSync(config.scenario, '{}');
    await app.page.getByRole('button', { name: '下載並驗證更新與回復包', exact: true }).click();
    const install = app.page.getByRole('button', { name: '結束程式並安裝 0.1.1', exact: true });
    await install.waitFor();
    assert.equal(await install.isDisabled(), true);
    const prepared = await app.invoke('update_state');
    await assert.rejects(() => app.invoke('install_update', { token: prepared.planToken, confirmed: false, rollback: false }));
    const next = path.join(config.cache, prepared.planToken, 'next.exe');
    assert.ok(path.resolve(next).startsWith(path.resolve(config.cache) + path.sep));
    const original = fs.readFileSync(next);
    fs.writeFileSync(next, 'synthetic corrupt installer');
    await assert.rejects(() => app.invoke('install_update', { token: prepared.planToken, confirmed: true, rollback: false }));
    assert.equal(app.child.exitCode, null);
    fs.writeFileSync(next, original);
    await app.page.getByLabel('我已儲存所有工作，現在可以結束回報工具').check();
    await install.click();
    await until(() => app.child.exitCode !== null, 'Confirmed update did not close owned client');
    await installed('0.1.1');
    app = await launch('0.1.1');
    const connection = await app.invoke('connection_settings');
    assert.equal(connection.endpoint, config.endpoint);
    assert.equal(connection.credentialConfigured, true);
    await app.page.locator('.update-panel summary').click();
    const rollback = app.page.getByRole('button', { name: '結束程式並回復 0.1.0', exact: true });
    await rollback.waitFor();
    assert.equal(await rollback.isDisabled(), true);
    await app.page.getByLabel('我已儲存所有工作，現在可以結束回報工具').check();
    await rollback.click();
    await until(() => app.child.exitCode !== null, 'Confirmed rollback did not close owned client');
    await installed('0.1.0');
    // Upgrade once more, then simulate an unusable new executable and stop HTTPS.
    app = await launch('0.1.0');
    await app.page.locator('.update-panel summary').click();
    await app.page.getByLabel('我已儲存所有工作，現在可以結束回報工具').check();
    await app.page.getByRole('button', { name: '結束程式並安裝 0.1.1', exact: true }).click();
    await until(() => app.child.exitCode !== null, 'Second confirmed update did not close owned client');
    await installed('0.1.1');
    fs.writeFileSync(config.scenario, JSON.stringify({ mode: 'offline' }));
    const servicePort = Number(new URL(config.endpoint).port);
    await until(() => new Promise(resolve => {
      const socket = net.createConnection({ host: '127.0.0.1', port: servicePort });
      socket.once('connect', () => { socket.destroy(); resolve(false); });
      socket.once('error', () => resolve(true));
    }), 'Owned HTTPS service did not stop');
    assert.equal(fs.realpathSync(path.dirname(executable)), fs.realpathSync(config.installation));
    fs.renameSync(executable, path.join(config.installation, 'synthetic-unlaunchable.exe'));
    const recovery = path.join(config.cache, prepared.planToken, 'recovery.exe');
    const helper = spawn(recovery, [], { stdio: 'ignore', windowsHide: true });
    owned.push(helper);
    execFileSync(config.python, ['-m', 'scripts.check_signed_updates', '--confirm-recovery', String(helper.pid),
      '--recovery-executable', recovery], { cwd: config.repo, windowsHide: true, timeout: 30000 });
    await until(() => helper.exitCode !== null, 'Recovery helper did not finish');
    await installed('0.1.0');
    console.log('PASS: real Tauri check/prepare, truncated/corrupt refusal, confirmation, upgrade, rollback and offline recovery with unusable new executable; credentials retained.');
  } catch (error) {
    console.error('Native acceptance assertion failed:', error);
    throw error;
  } finally {
    for (const child of owned) {
      if (child.exitCode === null) child.kill();
      await until(() => child.exitCode !== null || child.signalCode !== null, 'Owned test client failed to exit');
    }
  }
})().then(() => process.exit(0)).catch(error => { console.error(error); process.exit(1); });
