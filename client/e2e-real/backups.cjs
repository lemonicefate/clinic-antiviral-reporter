const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const {url}=JSON.parse(fs.readFileSync(path.join(process.env.LOCALAPPDATA,'ClinicReporterAcceptance/case-queue-v1/current.json')));
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const admin=await browser.newPage(), reporting=await browser.newPage(), controls=await browser.newPage();
  await controls.goto(url);
  await admin.goto(url+'app?profile=admin');
  await admin.getByLabel('操作身分',{exact:true}).fill('SYN-BACKUP-ADMIN');
  await admin.getByRole('button',{name:'連線',exact:true}).click();
  await admin.getByRole('button',{name:'備份與還原',exact:true}).click();
  const panel=admin.getByRole('region',{name:'中央備份狀態',exact:true});
  await panel.getByText('備份完成',{exact:true}).waitFor();
  await panel.getByText('本機合成測試；不構成正式異機備份證據。',{exact:true}).waitFor();
  assert.equal(/\\\\|tls\.key|BEGIN PRIVATE|Bearer/.test(await panel.innerText()),false);
  const before=await panel.getByTestId('backup-id').innerText();
  await panel.getByLabel('備份原因',{exact:true}).fill('Synthetic browser manual backup');
  await panel.getByRole('button',{name:'立即要求備份',exact:true}).click();
  await panel.getByText('備份要求已受理；請等候完成。',{exact:true}).waitFor();
  await admin.waitForFunction(previous=>{
    const id=document.querySelector('[data-testid="backup-id"]');
    return id && id.textContent!==previous && document.body.textContent.includes('備份完成');
  },before);
  await reporting.goto(url+'app?profile=reporting');
  await reporting.getByLabel('操作身分',{exact:true}).fill('SYN-REPORTER');
  await reporting.getByRole('button',{name:'連線',exact:true}).click();
  await reporting.getByRole('heading',{name:'回報管理清單',exact:true}).waitFor();
  assert.equal(await reporting.getByRole('button',{name:'備份與還原',exact:true}).count(),0);
  await admin.setViewportSize({width:720,height:900});
  assert.equal(await admin.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await controls.evaluate(()=>control('stop'));
  await admin.getByRole('button',{name:'連線',exact:true}).waitFor({timeout:15000});
  assert.equal(await panel.count(),0);
  console.log('PASS: real HTTPS scheduled/manual backup, private health, administrator navigation, responsive layout and outage clearing.');
 } finally {await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1;});
