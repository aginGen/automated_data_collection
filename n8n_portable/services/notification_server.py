from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timezone
import json, threading, os

LOG = Path(__file__).resolve().parent.parent / 'outputs' / 'lab5' / 'notifications.jsonl'
LOG.parent.mkdir(parents=True, exist_ok=True)
LOCK = threading.Lock()
PAGE = '''<!doctype html><html lang="ru"><meta charset="utf-8"><title>Лабораторная 5 — уведомления</title><style>body{font:18px system-ui;max-width:850px;margin:50px auto;padding:0 20px;background:#f3f5f8;color:#1b2838}h1{font-size:30px}.alert{background:#ffe6e6;border:3px solid #bd2222;border-radius:10px;padding:20px;margin:16px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}#empty{color:#506070}</style><h1>Лабораторная 5 — локальные уведомления</h1><p>Приёмник ошибок n8n, обновление каждые 2 секунды.</p><div id="alerts"></div><p id="empty">Уведомлений пока нет.</p><script>async function refresh(){try{const r=await fetch('/notifications',{cache:'no-store'});const items=await r.json();const a=document.getElementById('alerts');a.replaceChildren();document.getElementById('empty').hidden=items.length>0;for(const x of items.slice(-20).reverse()){const d=document.createElement('div');d.className='alert';d.setAttribute('role','alert');const h=document.createElement('strong');h.textContent='ОШИБКА СБОРА: '+x.stage;const pre=document.createElement('pre');pre.textContent='Время: '+x.timestamp+'\\nURL: '+x.url+'\\nСообщение: '+x.message;d.append(h,pre);a.append(d)}}catch(e){document.getElementById('empty').textContent='Приёмник недоступен';document.getElementById('empty').hidden=false}}refresh();setInterval(refresh,2000)</script></html>'''
class Handler(BaseHTTPRequestHandler):
 def respond(self, code, data, content_type):
  data=data.encode('utf-8'); self.send_response(code); self.send_header('Content-Type',content_type+'; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
 def do_GET(self):
  if self.path=='/health': return self.respond(200,json.dumps({'status':'ready','service':'lab5-notifications','pid':os.getpid(),'workspace':str(Path(__file__).resolve().parent.parent)}),'application/json')
  if self.path=='/': return self.respond(200,PAGE,'text/html')
  if self.path=='/notifications':
   with LOCK:
    rows=[]
    if LOG.exists():
     for line in LOG.read_text(encoding='utf-8').splitlines():
      try: rows.append(json.loads(line))
      except json.JSONDecodeError: pass
   return self.respond(200,json.dumps(rows[-100:],ensure_ascii=False),'application/json')
  return self.respond(404,'Not found','text/plain')
 def do_POST(self):
  if self.path!='/notify': return self.respond(404,'Not found','text/plain')
  try:
   length=int(self.headers.get('Content-Length','0'))
   if length<1 or length>4096: raise ValueError('invalid length')
   if self.headers.get_content_type()!='application/json': raise ValueError('expected application/json')
   data=json.loads(self.rfile.read(length))
   if not isinstance(data,dict) or set(data)!={'stage','url','message','timestamp'}: raise ValueError('invalid fields')
   if any(not isinstance(data[k],str) or not data[k].strip() or len(data[k])>1000 for k in data): raise ValueError('invalid values')
   data['received_at']=datetime.now(timezone.utc).isoformat()
   with LOCK:
    with LOG.open('a',encoding='utf-8') as f: f.write(json.dumps(data,ensure_ascii=False)+'\n')
   return self.respond(201,json.dumps({'received':True},ensure_ascii=False),'application/json')
  except (ValueError,UnicodeDecodeError,json.JSONDecodeError): return self.respond(400,'Invalid notification','text/plain')
if __name__=='__main__':
 print('Local notification dashboard: http://127.0.0.1:5686/',flush=True)
 ThreadingHTTPServer(('127.0.0.1',5686),Handler).serve_forever()
