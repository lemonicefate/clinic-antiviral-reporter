const {chromium}=require('playwright');
const fs=require('node:fs'), path=require('node:path'), assert=require('node:assert/strict');
(async()=>{
  const {url}=JSON.parse(fs.readFileSync(path.join(process.env.LOCALAPPDATA,'ClinicReporterAcceptance/case-queue-v1/current.json')));
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const control=await browser.newPage(), page=await browser.newPage();
    await control.goto(url);
    async function setSource(action){await control.evaluate(async(action)=>{const r=await fetch('/control',{method:'POST',headers:{'Content-Type':'application/json','X-Acceptance':token},body:JSON.stringify({action})});if(!r.ok)throw Error('Synthetic preparation failed');},action);}
    await page.goto(url+'app?profile=reporting');await page.getByLabel('操作身分',{exact:true}).fill('SYN-DR-A');
    await page.getByRole('button',{name:'連線',exact:true}).click();
    const panel=page.getByRole('region',{name:'來源掃描狀態',exact:true});
    await panel.getByText('掃描完成',{exact:true}).waitFor();
    await page.getByRole('row').filter({hasText:'SYN-DBF-ORDER-1'}).waitFor();
    await setSource('dbf-orphan');await panel.getByRole('button',{name:'要求檔案重掃',exact:true}).click();
    await panel.getByText('掃描有隔離來源',{exact:true}).waitFor();
    await page.getByRole('button',{name:'讀取隔離來源',exact:true}).click();
    await page.getByText('缺少父資料，等待重試',{exact:true}).waitFor();
    await page.getByRole('button',{name:'查詢清單',exact:true}).click();
    assert.ok((await page.getByRole('row').filter({hasText:'SYN-DBF-ORDER-1'}).innerText()).includes('HIS 異動待確認'));
    await setSource('dbf-valid');await panel.getByRole('button',{name:'要求檔案重掃',exact:true}).click();
    await panel.getByText('掃描完成',{exact:true}).waitFor();
    await page.getByRole('button',{name:'查詢清單',exact:true}).click();
    await page.getByRole('row').filter({hasText:'SYN-DBF-ORDER-1'}).waitFor();
    assert.equal(await page.getByRole('row').filter({hasText:'SYN-DBF-ORDER-1'}).count(),1);
    await page.setViewportSize({width:720,height:900});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true);
    await control.evaluate(()=>control('stop'));
    await page.getByRole('button',{name:'連線',exact:true}).waitFor({timeout:15000});
    assert.equal(await panel.count(),0);
    console.log('PASS: real DBF background scan, progress, orphan quarantine/retry, unchanged recovery without duplicate, layout and outage clearing.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1});
