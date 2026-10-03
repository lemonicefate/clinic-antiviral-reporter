const {chromium}=require('playwright');
const fs=require('node:fs'), path=require('node:path'), assert=require('node:assert/strict');
(async()=>{
  const {url}=JSON.parse(fs.readFileSync(path.join(process.env.LOCALAPPDATA,'ClinicReporterAcceptance/case-queue-v1/current.json')));
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const admin=await browser.newPage(), editor=await browser.newPage();
    async function connect(page,profile){await page.goto(url+'app?profile='+profile);await page.getByLabel('操作身分',{exact:true}).fill('SYN-DR-A');await page.getByRole('button',{name:'連線',exact:true}).click();}
    await connect(admin,'admin');await admin.getByRole('button',{name:'案件工作清單',exact:true}).click();
    await connect(editor,'reporting');
    async function refresh(scenario){await admin.getByLabel('合成來源情境',{exact:true}).selectOption(scenario);await admin.getByRole('button',{name:'刷新合成來源',exact:true}).click();await admin.getByRole('status').filter({hasText:'合成來源刷新完成'}).waitFor();}
    async function open(){await editor.getByRole('button',{name:'查詢清單',exact:true}).click();await editor.getByRole('row').filter({hasText:'SYN-ORDER-1'}).getByRole('button',{name:'核對此案',exact:true}).click();await editor.getByRole('region',{name:'HIS 來源核對',exact:true}).waitFor();}
    await refresh('modified');await open();
    const review=editor.getByRole('region',{name:'HIS 來源核對',exact:true});
    assert.ok((await review.innerText()).includes('合成病人甲（來源更正）'));
    assert.ok((await review.getByRole('row').filter({hasText:'來源數量'}).innerText()).includes('10'));
    await review.getByLabel('來源處理方式',{exact:true}).selectOption('retain');
    await review.getByLabel('來源核對原因',{exact:true}).fill('SYN retained original dispensing');
    await refresh('cancelled');
    await review.getByRole('button',{name:'儲存來源核對',exact:true}).click();
    await review.getByRole('alert').waitFor();
    assert.equal(await review.getByRole('button',{name:'儲存來源核對',exact:true}).isDisabled(),true);
    await review.getByRole('button',{name:'重新讀取來源與回報資料',exact:true}).click();
    await review.getByText('目前來源狀態：C',{exact:true}).waitFor();
    await review.getByLabel('來源處理方式',{exact:true}).selectOption('retain');
    await review.getByLabel('來源核對原因',{exact:true}).fill('SYN cancellation reviewed');
    await review.getByRole('button',{name:'儲存來源核對',exact:true}).click();
    await editor.getByText('來源核對已儲存，清單已更新。',{exact:true}).waitFor();
    await refresh('unseen');await open();
    await review.getByText(/來源尚未能可靠讀取/).waitFor();
    assert.equal(await review.getByRole('button',{name:'儲存來源核對',exact:true}).isDisabled(),true);
    await editor.getByRole('button',{name:'讀取隔離來源',exact:true}).click();
    await editor.getByText('尚未看診但存在醫令',{exact:true}).waitFor();
    await refresh('original');await open();
    await review.getByLabel('來源處理方式',{exact:true}).selectOption('update');
    await review.getByLabel('來源核對原因',{exact:true}).fill('SYN recovered source verified');
    await review.getByRole('button',{name:'儲存來源核對',exact:true}).click();
    await editor.getByText('來源核對已儲存，清單已更新。',{exact:true}).waitFor();
    console.log('PASS: source differences, concurrent refresh conflict, explicit retain/update, unresolved block, restricted diagnostics and recovery.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1});
