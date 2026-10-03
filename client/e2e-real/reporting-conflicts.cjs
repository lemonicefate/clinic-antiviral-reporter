const {chromium}=require('playwright');
const fs=require('node:fs'), path=require('node:path'), assert=require('node:assert/strict');
(async()=>{
  const {url}=JSON.parse(fs.readFileSync(path.join(process.env.LOCALAPPDATA,'ClinicReporterAcceptance/case-queue-v1/current.json')));
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const a=await browser.newPage(), b=await browser.newPage();
    async function connect(p){await p.goto(url+'app?profile=reporting');await p.getByLabel('操作身分',{exact:true}).fill('SYN-CONFLICT');await p.getByRole('button',{name:'連線',exact:true}).click();await p.getByRole('heading',{name:'回報管理清單'}).waitFor();}
    async function open(p,order){await p.getByRole('row').filter({hasText:order}).getByRole('button',{name:'核對此案',exact:true}).click();await p.getByLabel('實發數量',{exact:true}).waitFor();}
    await connect(a);await connect(b);await open(a,'SYN-ORDER-1');await open(b,'SYN-ORDER-1');
    await a.getByLabel('批號 1',{exact:true}).fill('SYN-CURRENT');
    await a.getByRole('button',{name:'儲存發藥核對',exact:true}).click();
    await a.getByText('回報核對已儲存，清單已更新。',{exact:true}).waitFor();
    await b.getByLabel('批號 1',{exact:true}).fill('SYN-STALE');
    await b.getByRole('button',{name:'儲存發藥核對',exact:true}).click();
    const conflict=b.getByRole('region',{name:'回報資料衝突',exact:true});
    await conflict.waitFor();
    assert.ok((await conflict.innerText()).includes('SYN-CURRENT'));
    assert.ok((await conflict.innerText()).includes('SYN-STALE'));
    assert.ok((await conflict.innerText()).includes('SYN-ORDER-1'));
    assert.equal(await b.getByRole('button',{name:'儲存發藥核對',exact:true}).isDisabled(),true);
    await b.getByRole('button',{name:'重新讀取回報資料',exact:true}).click();
    await b.waitForFunction(()=>document.querySelector('input[value="SYN-CURRENT"]'));
    await b.getByRole('button',{name:'查詢清單',exact:true}).click();
    await b.getByLabel('選取 SYN-ORDER-1',{exact:true}).check();
    await b.getByLabel('選取 SYN-ORDER-2',{exact:true}).check();
    await b.getByLabel('批次批號',{exact:true}).fill('SYN-BULK-STALE');
    await b.getByLabel('我已核對已選案件，確認取代其全部批號分攤',{exact:true}).check();
    await open(a,'SYN-ORDER-1');
    const reason=a.getByLabel('官方用藥對象',{exact:true});
    await reason.selectOption({index:1});
    await a.getByLabel(/我已核對 合成病人甲/).check();
    await a.getByRole('button',{name:'儲存用藥理由',exact:true}).click();
    await a.getByText('用藥理由已儲存，清單已更新。',{exact:true}).waitFor();
    await b.getByRole('button',{name:'套用批次批號',exact:true}).click();
    await conflict.waitFor();
    assert.ok((await conflict.innerText()).includes('SYN-ORDER-1'));
    assert.ok((await conflict.innerText()).includes('SYN-BULK-STALE'));
    assert.ok((await conflict.getByRole('row').filter({hasText:'用藥理由'}).innerText()).includes('1:「流感併發重症」'));
    assert.equal(await b.getByRole('button',{name:'套用批次批號',exact:true}).isDisabled(),true);
    await b.getByRole('button',{name:'查詢清單',exact:true}).click();
    await open(b,'SYN-ORDER-2');
    assert.equal(await b.getByLabel('批號 1',{exact:true}).inputValue(),'SYN-SHARED');
    console.log('PASS: individual and bulk conflicts show case/current/draft differences, block stale writes, require reload; reason-only concurrent edit is visible and batch stays atomic.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1});
