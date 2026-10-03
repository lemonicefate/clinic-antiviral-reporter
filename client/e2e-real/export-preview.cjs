const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
  const {url}=JSON.parse(fs.readFileSync(path.join(process.env.LOCALAPPDATA,'ClinicReporterAcceptance/case-queue-v1/current.json')));
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const page=await browser.newPage(), control=await browser.newPage();
    await control.goto(url);
    await page.goto(url+'app?profile=reporting');
    await page.evaluate(async()=>{
      const invoke=window.__TAURI_INTERNALS__.invoke;
      let sessionId;
      async function request(path,method='GET',body=null){
        const response=await invoke('central_request',{request:{path,method,body,sessionId}});
        return {status:response.status,data:JSON.parse(response.body)};
      }
      const session=await request('/api/v1/sessions','POST',{requestId:crypto.randomUUID(),expectedRevision:0,operator:'SYN-PREVIEW-SETUP'});
      sessionId=session.data.sessionId;
      const queue=await request('/api/v1/cases?physician=');
      let item=queue.data.items.find(item=>item.sourceOrder==='SYN-ORDER-1');
      async function save(suffix,fields){
        const response=await request('/api/v1/cases/'+item.caseId+suffix,'POST',{
          requestId:crypto.randomUUID(),expectedRevision:item.revision,...fields});
        if(response.status!==200)throw Error('Synthetic preview preparation failed');
        item=response.data;
      }
      if(item.excluded)await save('/exclusion',{excluded:false,reason:'Synthetic preview preparation'});
      if(item.sourceReviewRequired)await save('/source-review',{sourceSnapshot:item.latestSourceSnapshot,resolution:'update',reason:'Synthetic preview source verification'});
      await save('/reason',{reason:'23:未滿5歲及65歲以上之類流感患者',patientConfirmed:true});
      await save('/dispensing',{reportedQuantity:item.sourceQuantity,lots:[{lot:'SYN-PREVIEW-LOT',quantity:item.sourceQuantity}],changeReason:'Synthetic preview verification'});
      const denied=await request('/api/v1/exports','POST',{requestId:crypto.randomUUID(),expectedRevision:0,cases:[{caseId:item.caseId,expectedRevision:item.revision}]});
      if(denied.status!==403||denied.data.detail.code!=='production_export_gated')throw Error('Production generation gate failed');
      if((await request('/api/v1/exports/'+crypto.randomUUID()+'/file')).status!==403)throw Error('Production download gate failed');
    });
    await page.getByLabel('操作身分',{exact:true}).fill('SYN-PREVIEW-REPORTER');
    await page.getByRole('button',{name:'連線',exact:true}).click();
    await page.getByRole('button',{name:'匯出前核對',exact:true}).click();
    const panel=page.getByRole('region',{name:'匯出前核對',exact:true});
    const selected=panel.getByLabel('選取 SYN-ORDER-1',{exact:true});
    await selected.waitFor();
    assert.equal(await selected.isChecked(),true);
    assert.equal(await panel.getByRole('button',{name:'產生正式 Excel',exact:true}).isDisabled(),true);
    assert.equal(await panel.getByRole('button',{name:'下載正式 Excel',exact:true}).isDisabled(),true);
    await panel.getByText('OPEN：官方必填／條件必填、數量、多批號與補正規則',{exact:true}).waitFor();
    await panel.getByRole('button',{name:'清除選取',exact:true}).click();
    await panel.getByRole('status').filter({hasText:'目前選取 0 筆'}).waitFor();
    await selected.click();
    await panel.getByRole('status').filter({hasText:'目前選取 1 筆'}).waitFor();
    assert.equal(await selected.isChecked(),true);
    await page.setViewportSize({width:720,height:900});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await control.evaluate(()=>control('stop'));
    await page.getByRole('button',{name:'連線',exact:true}).waitFor({timeout:15000});
    assert.equal(await panel.count(),0);
    console.log('PASS: real HTTPS export preview, preselection/manual clearing, readable OPEN gates, blocked generation/download, layout and outage clearing.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1});
