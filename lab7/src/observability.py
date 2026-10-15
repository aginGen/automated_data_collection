import json
import statistics
import threading
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path


class Journal:
    def __init__(self,path,run_id):
        self.path,self.run_id=Path(path),run_id
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.rows,self.lock=[],threading.Lock()

    def write(self,event,**values):
        row=dict(ts=datetime.now(timezone.utc).isoformat(),run_id=self.run_id,event=event,
                 host='',url='',status=None,ms=0.0,attempt=0,bytes=0,error='')
        row.update(values)
        with self.lock:
            self.rows.append(row)
            with self.path.open('a',encoding='utf-8') as file:
                file.write(json.dumps(row,ensure_ascii=False)+'\n')


THRESHOLDS={
    'error_share':(0.20,'Не более 20% неуспешных HTTP-ответов'),
    'rate_or_block_share':(0.10,'Не более 10% ответов 429/403'),
    'p95_ms':(2000.0,'95% запросов должны укладываться в две секунды'),
    'volume_drop':(0.20,'Падение числа записей не более 20% от медианы истории'),
    'body_size_drop':(0.30,'Падение размера ответа не более 30% от медианы истории'),
    'blocked_domains':(0,'Любая блокировка останавливает сбор домена'),
}


def report(rows,records,duration,history=()):
    requests=[r for r in rows if r['event']=='request']
    count=len(requests)
    codes=Counter(str(r['status']) for r in requests)
    latency=sorted(r['ms'] for r in requests)
    errors=sum(r['status'] is None or r['status']>=400 for r in requests)
    sizes=[r.get('decoded_bytes',0) for r in requests if r['status']==200 and r.get('resource')=='records']
    body_mean=statistics.mean(sizes) if sizes else 0.0
    result=dict(requests=count,codes=dict(codes),error_share=errors/max(count,1),
                rate_or_block_share=sum(r['status'] in (429,403) for r in requests)/max(count,1),
                retries=sum(r['event']=='retry' for r in rows),
                median_ms=statistics.median(latency) if latency else 0,
                p95_ms=statistics.quantiles(latency,n=100,method='inclusive')[94] if len(latency)>1 else (latency[0] if latency else 0),
                wire_bytes=sum(r['bytes'] for r in requests),decoded_bytes=sum(r.get('decoded_bytes',0) for r in requests),
                not_modified=codes.get('304',0),
                breaker_activations=sum(r['event']=='circuit_open' for r in rows),
                blocked_domains=len({r['host'] for r in rows if r['event']=='blocked_domain'}),
                records=records,rejected=sum(r['event']=='reject' for r in rows),
                duration_s=round(duration,4),mean_body_bytes=body_mean,volume_drop=0.0,body_size_drop=0.0)
    if history:
        median_volume=statistics.median(r['records'] for r in history)
        result['volume_drop']=max(0.0,1-records/max(1,median_volume))
        historical_sizes=[r['mean_body_bytes'] for r in history if r['mean_body_bytes']]
        if historical_sizes and sizes:
            result['body_size_drop']=max(0.0,1-body_mean/statistics.median(historical_sizes))
    result['alerts']=[dict(metric=k,value=result[k],threshold=v[0],reason=v[1])
                      for k,v in THRESHOLDS.items() if result[k]>v[0]]
    result['verdict']='red' if result['alerts'] else 'green'
    return result
