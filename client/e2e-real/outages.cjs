const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
  const {url}=JSON.parse(fs.readFileSync(path.join(process.env.LOCALAPPDATA,'ClinicReporterAcceptance/case-queue-v1/current.json')));
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const page=await browser.newPage(), controlPage=await browser.newPage();
    await controlPage.goto(url);await controlPage.evaluate(()=>control('start'));
    async function connect(){
      await page.getByLabel('操作身分',{exact:true}).fill('SYN-RECOVERY-ADMIN');
      await page.getByRole('button',{name:'連線',exact:true}).click();
      await page.getByRole('button',{name:'案件工作清單',exact:true}).click();
      await page.getByLabel('醫師篩選').selectOption('');
      await page.getByRole('button',{name:'查詢清單',exact:true}).click();
    }
    await page.goto(url+'app?profile=admin');await connect();
    const scan=page.getByRole('region',{name:'來源掃描狀態',exact:true});
    await scan.getByText('掃描完成',{exact:true}).waitFor();
    await scan.getByLabel('停機復原補掃（管理者）').check();
    await scan.getByRole('button',{name:'要求檔案重掃',exact:true}).click();
    await scan.getByText('掃描完成',{exact:true}).waitFor();
    await page.getByRole('button',{name:'查詢清單',exact:true}).click();
    const row=page.getByRole('row').filter({hasText:'SYN-DBF-ORDER-1'});
    await row.getByRole('button',{name:'核對此案'}).click();
    let panel=page.getByRole('region',{name:'系統外完成補記',exact:true});
    await panel.getByRole('button',{name:'讀取補掃結果',exact:true}).click();
    await panel.getByLabel('補記原因',{exact:true}).fill('SYN-OUTAGE-DRAFT');
    await controlPage.evaluate(()=>control('stop'));
    await page.getByRole('button',{name:'連線',exact:true}).waitFor({timeout:15000});
    assert.equal(await panel.count(),0);
    assert.equal(await page.getByText('SYN-DBF-P1',{exact:true}).count(),0);
    assert.equal(await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}).includes('SYN-OUTAGE-DRAFT')),false);
    await controlPage.evaluate(()=>control('start'));await connect();
    await row.getByRole('button',{name:'核對此案'}).click();
    panel=page.getByRole('region',{name:'系統外完成補記',exact:true});
    assert.equal(await panel.getByLabel('補記原因',{exact:true}).inputValue(),'');
    await panel.getByRole('button',{name:'讀取補掃結果',exact:true}).click();
    await panel.getByText(/補掃範圍：/).waitFor();
    await panel.getByLabel('補記原因',{exact:true}).fill('Synthetic paper and SMIS workflow completed');
    await panel.getByLabel('已核對此來源醫令，確認停機期間已依紙本及 SMIS 完成').check();
    await panel.getByRole('button',{name:'確認系統外已完成',exact:true}).click();
    await page.getByText('系統外完成已補記，清單已更新。',{exact:true}).waitFor();
    assert.equal(await row.count(),0);
    await page.getByLabel('狀態篩選',{exact:true}).selectOption('outside_completed');
    await page.getByRole('button',{name:'查詢清單',exact:true}).click();
    await row.getByRole('button',{name:'核對此案'}).click();
    await page.getByText('Synthetic paper and SMIS workflow completed',{exact:true}).waitFor();
    assert.equal(await page.getByRole('button',{name:'確認系統外已完成',exact:true}).count(),0);
    assert.ok((await row.innerText()).includes('系統外已完成'));
    await page.setViewportSize({width:720,height:900});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.getByRole('button',{name:'關閉案件',exact:true}).click();
    // Delay a real authorized detail at the native bridge boundary until offline.
    await page.evaluate(()=>{
      const invoke=window.__TAURI_INTERNALS__.invoke;
      window.__TAURI_INTERNALS__.invoke=async function(command,args){
        const result=await invoke(command,args);
        if(command==='central_request' && /^\/api\/v1\/cases\/[a-f0-9-]+$/.test(args.request.path)){
          await new Promise(resolve=>{window.releaseSyntheticDetail=resolve;});
        }
        return result;
      };
    });
    await row.getByRole('button',{name:'核對此案'}).click();
    await page.waitForFunction(()=>typeof window.releaseSyntheticDetail==='function');
    await controlPage.evaluate(()=>control('stop'));
    await page.getByRole('button',{name:'連線',exact:true}).waitFor({timeout:15000});
    await page.evaluate(async()=>{
      window.releaseSyntheticDetail();
      await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    });
    assert.equal(await page.getByRole('region',{name:'系統外完成紀錄',exact:true}).count(),0);
    assert.equal(await page.getByText('Synthetic paper and SMIS workflow completed',{exact:true}).count(),0);
    console.log('PASS: real HTTPS admin recovery rescan, outage clears draft and late detail, authorized reconnect, outside completion and terminal history.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1});
