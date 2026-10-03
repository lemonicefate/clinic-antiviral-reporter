"""Local browser acceptance harness using repository service, built UI and synthetic state.

Run from the repository venv. Never use this harness with clinical data. It models
separate device identities in memory, not native Windows Credential Manager.
"""
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread, RLock
from urllib.request import Request, build_opener, HTTPSHandler, ProxyHandler
from urllib.error import HTTPError
from urllib.parse import urlsplit, parse_qs
from uuid import uuid4
import json
import mimetypes
import secrets
import socket
import ssl
import time
import ipaddress

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import uvicorn
import os
import sys
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from service.app import create_app
from service.settings import Settings
from service.provision import initialize_administrator
from service.cases import clinic_today
from scripts.synthetic_dbf import prepare as prepare_dbf

ROOT = Path(os.environ['LOCALAPPDATA']) / 'ClinicReporterAcceptance' / 'case-queue-v1'
ROOT.mkdir(parents=True, exist_ok=True)
WEB = REPO / 'client' / 'dist'
if not (WEB / 'index.html').is_file():
    raise SystemExit('Build client first: npm run build')
RUN = ROOT / ('run-' + uuid4().hex[:8])
RUN.mkdir()
TOKEN = secrets.token_urlsafe(32)
LOCK = RLock()
def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]
TLS_PORT = port()
ENDPOINT = f'https://127.0.0.1:{TLS_PORT}'
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Local synthetic acceptance only')])
now = datetime.now(timezone.utc)
cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
        .not_valid_after(now+timedelta(days=2))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256()))
(RUN/'tls.crt').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
(RUN/'tls.key').write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
settings = Settings.from_environment({
    'CLINIC_REPORTER_STATE_DIR': str(RUN/'state'),
    'CLINIC_REPORTER_HIS_SOURCE_PATH': r'\\synthetic-his\data',
    'CLINIC_REPORTER_BACKUP_ROOT': r'\\synthetic-his\backup',
    'CLINIC_REPORTER_EXPORT_ENABLED': 'false',
    'CLINIC_REPORTER_SYNTHETIC_ENABLED': 'true',
    'CLINIC_REPORTER_SYNTHETIC_DBF_ENABLED': os.environ.get('CLINIC_ACCEPTANCE_DBF', 'false'),
    'CLINIC_REPORTER_HIS_SCAN_FROM_DATE': clinic_today().isoformat(),
})
if settings.synthetic_dbf_enabled:
    prepare_dbf(RUN/'state', clinic_today())
identities = {'admin': {'active': secrets.token_urlsafe(32)}, 'doctor': {}, 'reporting': {}, 'new': {}}
initialize_administrator(settings, '測試管理電腦 A', identities['admin']['active'])
opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context(cafile=str(RUN/'tls.crt'))))
server = None
worker = None
def call(path, method='GET', body=None, credential=None, session=None):
    headers = {'Content-Type': 'application/json'}
    if credential:
        headers['Authorization'] = 'Bearer ' + credential
    if session:
        headers['X-Session-Id'] = session
    request = Request(ENDPOINT + path, method=method, headers=headers,
                      data=json.dumps(body).encode() if body is not None else None)
    try:
        response = opener.open(request, timeout=5)
    except HTTPError as error:
        response = error
    with response:
        return {'status': response.status, 'body': response.read().decode()}

def start():
    global server, worker
    if worker and worker.is_alive():
        return
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host='127.0.0.1', port=TLS_PORT,
                            ssl_certfile=str(RUN/'tls.crt'), ssl_keyfile=str(RUN/'tls.key'),
                            access_log=False, log_level='critical'))
    worker = Thread(target=server.run, daemon=True)
    worker.start()
    for _ in range(100):
        if server.started:
            return
        if not worker.is_alive():
            raise RuntimeError('Test central failed to start')
        time.sleep(.1)
    raise RuntimeError('Test central startup timeout')

def stop():
    if worker and worker.is_alive():
        assert server is not None
        server.should_exit = True
        worker.join(10)
        if worker.is_alive():
            raise RuntimeError('Test central is still stopping')

start()
admin_session = json.loads(call('/api/v1/sessions', 'POST', {
    'requestId': str(uuid4()), 'expectedRevision': 0, 'operator': '合成環境準備'}, identities['admin']['active'])['body'])
if settings.synthetic_dbf_enabled:
    assert call('/api/v1/mappings', 'POST', {
        'requestId': str(uuid4()), 'expectedRevision': 0,
        'effectiveFrom': clinic_today().isoformat() + 'T00:00:00+08:00',
        'initialDateFrom': clinic_today().isoformat(), 'enabled': True,
        'reason': 'Explicit temporary synthetic DBF acceptance setup'},
        identities['admin']['active'], admin_session['sessionId'])['status'] == 200
grant = json.loads(call('/api/v1/pairings', 'POST', {
    'requestId': str(uuid4()), 'expectedRevision': 0, 'capabilities': ['physician']},
    identities['admin']['active'], admin_session['sessionId'])['body'])
identities['doctor']['active'] = secrets.token_urlsafe(32)
enrolled = call('/api/v1/devices/enroll', 'POST', {
    'requestId': str(uuid4()), 'expectedRevision': 0, 'pairingCode': grant['pairingCode'],
    'name': '測試醫師電腦 B', 'credential': identities['doctor']['active']})
assert enrolled['status'] == 200
reporting_grant = json.loads(call('/api/v1/pairings', 'POST', {
    'requestId': str(uuid4()), 'expectedRevision': 0, 'capabilities': ['reporting']},
    identities['admin']['active'], admin_session['sessionId'])['body'])
identities['reporting']['active'] = secrets.token_urlsafe(32)
assert call('/api/v1/devices/enroll', 'POST', {
    'requestId': str(uuid4()), 'expectedRevision': 0, 'pairingCode': reporting_grant['pairingCode'],
    'name': '測試回報電腦 D', 'credential': identities['reporting']['active']})['status'] == 200
seeded = call('/api/v1/synthetic/refresh', 'POST', {
    'requestId': str(uuid4()), 'expectedRevision': 0}, identities['admin']['active'], admin_session['sessionId'])
assert seeded['status'] == 200


PAGE = '''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>本機操作驗收</title>
<style>body{font:18px/1.7 'Segoe UI','Microsoft JhengHei',sans-serif;max-width:900px;margin:35px auto;padding:20px;color:#203242;background:#f4f6f8}button,a.entry{font:inherit;padding:12px 18px;margin:8px 8px 8px 0;display:inline-block;background:#175579;color:white;border:0;border-radius:5px;text-decoration:none;cursor:pointer}section{background:white;padding:20px;margin:15px 0;border:1px solid #cbd3db}strong{color:#175579}li{margin:8px 0}</style>
<h1>案件工作清單驗收</h1><p>已準備好 4 筆合成案件。只在這台電腦運作，不連 HIS、不匯出 Excel。</p>
<p>使用目前專案的畫面及真正中央 API；瀏覽器入口取代 Windows 憑證保管。本次不驗收原生安裝、Windows 憑證或兩台實體電腦互連。</p>
<section><h2>先打開 A、B 兩個分頁</h2>
<a class="entry" href="/app?profile=admin" target="_blank">A：管理者</a>
<a class="entry" href="/app?profile=doctor" target="_blank">B：醫師</a>
<a class="entry" href="/app?profile=new" target="_blank">C：尚未配對</a>
<a class="entry" href="/app?profile=reporting" target="_blank">D：回報管理</a>
<p>A、B 的位址和通行證已準備好。操作身分請填 SYN-DR-A，保留「使用已配對裝置」，按「連線」。A 請再點「案件工作清單」；B 會直接顯示清單。</p></section>
<section><h2>照這個順序試</h2><ol>
<li><strong>預設清單：</strong>B 輸入 SYN-DR-A 連線，應有 3 案；跨日未完成 1 案，病歷號 SYN-0002 優先。SYN-0001 應有 2 案，各有不同醫令及同日多筆提醒。</li>
<li><strong>醫師篩選：</strong>選 SYN-DR-B，按「查詢清單」，應有 1 案 SYN-0003。選全部醫師再查詢應有 4 案。</li>
<li><strong>完整病歷號：</strong>在 SYN-DR-B 篩選下輸入 SYN-0001 並查詢，應跨醫師找到 2 案；改輸入 0001 應為 0 案。清空病歷號可回醫師篩選。</li>
<li><strong>逐案核對：</strong>搜尋 SYN-0001，點第一筆「核對此案」。焦點應到「核對案件」，可核對姓名、病歷號、出生日期、醫師及獨立來源醫令；來源量與回報量皆為 10 顆。另一筆醫令不應被自動代選。可展開原始來源。</li>
<li><strong>刷新去重：</strong>A 在案件清單選全部醫師並查詢，按「刷新合成來源」。應顯示新增 0、未變 4，總數仍為 4。B 不應有刷新合成來源按鈕。</li>
<li><strong>斷線與恢復：</strong>B 保持案件詳情開啟，再按下方「停止測試中央」。約十秒內 B 應清除姓名、清單及詳情，回連線頁並提示紙本。按「啟動測試中央」，B 重新連線應恢復 3 案且跨日案仍在。</li>
<li><strong>操作感受：</strong>請用 Tab／Enter 選案與搜尋，將視窗縮至平常診間寬度，確認文字可辨識、不會誤選另一筆；回報任何不好操作的位置。</li>
</ol><p>上述可自動判定的流程已由助理測試，不必重做。看到結果不符時，告訴我「第幾步、按了什麼、看到什麼」。</p></section>
<section><h2>用藥理由與衝突（已自動驗證）</h2><p>B 醫師開啟案件後，選取官方用藥對象，勾選核對病人及醫令，再按「儲存用藥理由」。待填理由筆數應減少，案件仍待回報核對，不代表可匯出。</p><p>若要觀察衝突，可同時開兩個 B 分頁並先讀取同一案；第一個儲存後，第二個修改會顯示中央最新理由及本次選取，必須重新讀取、核對後才能再存。未存表單在斷線時清除。</p></section>
<section><h2>停機練習控制</h2><p id="status" role="status">讀取中…</p>
<button onclick="control('stop')">停止測試中央</button><button onclick="control('start')">啟動測試中央</button>
<p>只控制本次測試中央；關閉此分頁不會停止它。測完可按「結束整個測試環境」。</p>
<button onclick="control('quit')">結束整個測試環境</button></section>
<script>const token=__TOKEN__;async function refresh(){try{const r=await fetch('/status');const d=await r.json();document.querySelector('#status').textContent=d.running?'測試中央：運作中':'測試中央：已停止';}catch{}}
async function control(action){const s=document.querySelector('#status');s.textContent='處理中…';try{const r=await fetch('/control',{method:'POST',headers:{'Content-Type':'application/json','X-Acceptance':token},body:JSON.stringify({action})});if(!r.ok)throw Error();if(action==='quit'){s.textContent='測試環境已結束。可以關閉所有測試分頁。';clearInterval(timer);}else await refresh();}catch{s.textContent='操作未完成，請告訴助理。';}}const timer=setInterval(refresh,3000);refresh();</script></html>'''

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def send(self, value, status=200, mime='application/json; charset=utf-8'):
        data = value if isinstance(value, bytes) else (json.dumps(value, ensure_ascii=False).encode() if not isinstance(value,str) else value.encode())
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def valid_host(self):
        address = self.server.server_address
        return isinstance(address, tuple) and self.headers.get('Host') == f'127.0.0.1:{address[1]}'
    def do_GET(self):
        if not self.valid_host():
            return self.send({},403)
        parsed = urlsplit(self.path)
        if parsed.path == '/':
            return self.send(PAGE.replace('__TOKEN__', json.dumps(TOKEN)), mime='text/html; charset=utf-8')
        if parsed.path == '/status':
            return self.send({'running': bool(worker and worker.is_alive())})
        if parsed.path == '/app':
            profile = parse_qs(parsed.query).get('profile',[''])[0]
            if profile not in identities:
                return self.send({},404)
            bridge = '''<script>window.__TAURI_INTERNALS__={invoke:async function(command,args){const r=await fetch('/invoke',{method:'POST',headers:{'Content-Type':'application/json','X-Acceptance':TOKEN},body:JSON.stringify({profile:PROFILE,command,args:args||{}})});const data=await r.json();if(!r.ok)throw new Error(data.error||'測試中央無法連線');return data;}};</script>'''.replace('TOKEN',json.dumps(TOKEN)).replace('PROFILE',json.dumps(profile))
            html = (WEB/'index.html').read_text(encoding='utf-8').replace('<head>', '<head>'+bridge)
            banner = '<div style="padding:8px;background:#fff1bf;text-align:center">假資料驗收 · '+{'admin':'A 管理者','doctor':'B 醫師','reporting':'D 回報管理','new':'C 新裝置'}[profile]+' · <a href="/" target="_blank">回驗收說明／停機控制</a></div>'
            return self.send(html.replace('<body>','<body>'+banner), mime='text/html; charset=utf-8')
        if parsed.path.startswith('/assets/'):
            path = (WEB/parsed.path.lstrip('/')).resolve()
            if path.is_relative_to((WEB/'assets').resolve()) and path.is_file():
                return self.send(path.read_bytes(), mime=mimetypes.guess_type(path)[0] or 'application/octet-stream')
        self.send({},404)
    def do_POST(self):
        if not self.valid_host() or self.headers.get('X-Acceptance') != TOKEN:
            return self.send({},403)
        try:
            size = int(self.headers.get('Content-Length','0'))
            if not 0 < size < 20000:
                return self.send({},400)
            data = json.loads(self.rfile.read(size))
            with LOCK:
                if self.path == '/control':
                    if data['action'] == 'start': start()
                    elif data['action'] == 'stop': stop()
                    elif data['action'] in ('dbf-valid', 'dbf-orphan') and settings.synthetic_dbf_enabled:
                        prepare_dbf(RUN/'state', clinic_today(), data['action'].removeprefix('dbf-'))
                    elif data['action'] == 'quit':
                        stop()
                        Thread(target=self.server.shutdown,daemon=True).start()
                    else: raise ValueError()
                    return self.send({'ok':True})
                if self.path != '/invoke': return self.send({},404)
                who = identities[data['profile']]
                command, args = data['command'], data['args']
                if command == 'connection_settings':
                    return self.send({'endpoint':ENDPOINT,'credentialConfigured':bool(who.get('active'))})
                if command == 'configure_connection':
                    if args['endpoint'].rstrip('/') != ENDPOINT or args.get('credential'):
                        raise ValueError('Only the prepared synthetic connection is allowed')
                    return self.send(None)
                if command == 'prepare_identity':
                    rid=args['requestId']
                    if who.get('pending_id') != rid and who.get('last') != rid:
                        who.update(pending_id=rid,pending=secrets.token_urlsafe(32))
                    return self.send(None)
                if command != 'central_request': raise ValueError()
                req = args['request']
                path = req['path']
                import re
                if not re.fullmatch(r'/api/v1/(sessions|session|devices|pairings|audit|mappings|devices/enroll|devices/[a-f0-9-]+/revoke|synthetic/refresh|reason-options|source-quarantine|scans|scans/status|cases|cases/bulk-lot|cases/[a-f0-9-]+|cases/[a-f0-9-]+/(reason|dispensing|exclusion|history|source-review))',urlsplit(path).path):
                    raise ValueError()
                if req['method'] not in ('GET','POST'): raise ValueError()
                body = req.get('body')
                if path == '/api/v1/devices/enroll':
                    rid = body['requestId']
                    credential = who.get('active') if who.get('last') == rid else who.get('pending') if who.get('pending_id') == rid else None
                    if not credential: raise ValueError()
                    body['credential']=credential
                    result=call(path,req['method'],body)
                    if result['status']==200:
                        who.update(active=credential,last=rid)
                        who.pop('pending',None)
                        who.pop('pending_id',None)
                else:
                    if not who.get('active'): raise ValueError()
                    result=call(path,req['method'],body,who['active'],req.get('sessionId'))
                return self.send(result)
        except Exception:
            self.send({'error':'測試操作未完成；請確認測試中央已啟動及裝置授權。'},503)

http = ThreadingHTTPServer(('127.0.0.1',0),Handler)
url=f'http://127.0.0.1:{http.server_port}/'
(ROOT/'current.json').write_text(json.dumps({'url':url,'run':str(RUN)}),encoding='utf-8')
try:
    http.serve_forever()
finally:
    http.server_close()
    stop()
