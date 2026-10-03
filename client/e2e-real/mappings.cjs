const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
  const {url}=JSON.parse(fs.readFileSync(path.join(process.env.LOCALAPPDATA,'ClinicReporterAcceptance/case-queue-v1/current.json')));
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const first=await browser.newPage(), second=await browser.newPage(), reporter=await browser.newPage();
    async function connect(page,profile){
      await page.goto(url+'app?profile='+profile);
      await page.getByLabel('操作身分',{exact:true}).fill('SYN-MAPPING-ADMIN');
      await page.getByRole('button',{name:'連線',exact:true}).click();
    }
    await connect(first,'admin');
    await first.getByRole('button',{name:'映射與啟用設定',exact:true}).click();
    await first.getByText('尚未設定啟用時間',{exact:true}).waitFor();
    await first.getByText('OPEN：實際 HIS 來源鍵、欄位及唯讀行為驗證',{exact:true}).waitFor();
    await first.getByText('OPEN：官方格式、數量、多批號及補正規則',{exact:true}).waitFor();
    await first.getByText('OPEN：合成資料實際通過 SMIS 匯入',{exact:true}).waitFor();
    assert.equal(await first.getByLabel('生效日期（台灣時間 00:00）',{exact:true}).inputValue(),'');
    await first.getByLabel('生效日期（台灣時間 00:00）',{exact:true}).fill('2026-10-01');
    await first.getByLabel('初始掃描起日',{exact:true}).fill('2026-10-01');
    await first.getByLabel('設定原因',{exact:true}).fill('SYN explicit go-live');
    await first.getByRole('button',{name:'儲存新版本',exact:true}).click();
    await first.getByText('目前設定版本：1',{exact:true}).waitFor();
    await connect(second,'admin');
    await second.getByRole('button',{name:'映射與啟用設定',exact:true}).click();
    await second.getByText('目前設定版本：1',{exact:true}).waitFor();
    for (const page of [first,second]) {
      await page.getByLabel('生效日期（台灣時間 00:00）',{exact:true}).fill('2026-10-02');
      await page.getByLabel('設定原因',{exact:true}).fill('SYN mapping replacement');
      await page.getByLabel('啟用此版本的映射',{exact:true}).uncheck();
    }
    await first.getByRole('button',{name:'儲存新版本',exact:true}).click();
    await first.getByText('目前設定版本：2',{exact:true}).waitFor();
    await second.getByRole('button',{name:'儲存新版本',exact:true}).click();
    await second.getByRole('status').filter({hasText:'其他管理者已變更設定'}).waitFor();
    assert.equal(await second.getByRole('button',{name:'儲存新版本',exact:true}).isDisabled(),true);
    assert.equal(await second.getByLabel('設定原因',{exact:true}).inputValue(),'SYN mapping replacement');
    await second.getByRole('button',{name:'重新載入並核對',exact:true}).click();
    await second.getByText('目前設定版本：2',{exact:true}).waitFor();
    assert.equal(await second.getByRole('article').count(),2);
    await second.setViewportSize({width:720,height:900});
    assert.equal(await second.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await connect(reporter,'reporting');
    assert.equal(await reporter.getByRole('button',{name:'映射與啟用設定',exact:true}).count(),0);
    console.log('PASS: real HTTPS explicit mapping activation, immutable version history, concurrent conflict, restricted navigation and layout.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1});
