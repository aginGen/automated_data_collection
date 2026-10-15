import argparse
import copy
import hashlib
import json
import sqlite3
from datetime import datetime,timezone
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]


def load(rows,rejects,database):
    rows=[dict(r,collected_at=datetime.fromisoformat(r['collected_at'].replace('Z','+00:00')).astimezone(timezone.utc).isoformat()) for r in rows]
    now=datetime.now(timezone.utc).isoformat()
    Path(database).parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(database) as db:
        db.executescript((ROOT/'db/schema.sql').read_text(encoding='utf-8'))
        authors={}
        for r in rows:
            previous=authors.get(r['author_key'])
            birth=r['author_birth_year'] if r['author_birth_year'] is not None else (previous[2] if previous else None)
            authors[r['author_key']]=(r['author_key'],r['author'],birth)
        db.executemany('INSERT INTO authors VALUES(?,?,?) ON CONFLICT(author_key) DO UPDATE SET '
                       'name=excluded.name,birth_year=COALESCE(excluded.birth_year,authors.birth_year)',
                       list(authors.values()))
        old=dict(db.execute('SELECT business_key,payload_hash FROM quotes'))
        changed=[]
        for r in rows:
            payload=json.dumps(r,ensure_ascii=False,sort_keys=True)
            digest=hashlib.sha256(payload.encode()).hexdigest()
            if old.get(r['business_key'])!=digest:
                changed.append((r,payload,digest))
        sql="""INSERT INTO quotes(business_key,text,author_key,source,source_url,parser_version,source_record_id,collected_at,updated_at,text_length,tags_json,payload_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(business_key) DO UPDATE SET text=excluded.text,
        author_key=excluded.author_key,source=excluded.source,source_url=excluded.source_url,
        parser_version=excluded.parser_version,source_record_id=excluded.source_record_id,
        collected_at=excluded.collected_at,updated_at=excluded.updated_at,
        text_length=excluded.text_length,tags_json=excluded.tags_json,payload_hash=excluded.payload_hash
        WHERE quotes.payload_hash<>excluded.payload_hash"""
        db.executemany(sql,[(r['business_key'],r['text'],r['author_key'],r['source'],r['source_url'],
                            r['parser_version'],r['source_record_id'],r['collected_at'],now,r['text_length'],
                            json.dumps(r['tags'],ensure_ascii=False),h) for r,p,h in changed])
        db.executemany('DELETE FROM quote_tags WHERE business_key=?',[(r['business_key'],) for r,p,h in changed])
        db.executemany('INSERT INTO quote_tags VALUES(?,?)',
                       [(r['business_key'],tag) for r,p,h in changed for tag in r['tags']])
        db.executemany('INSERT INTO quote_history(business_key,observed_at,payload_hash,payload) VALUES(?,?,?,?)',
                       [(r['business_key'],now,h,p) for r,p,h in changed])
        rejected=[]
        for r in rejects:
            payload=json.dumps(r['payload'],ensure_ascii=False,sort_keys=True,default=str)
            key=hashlib.sha256((payload+r['field']+r['reason']).encode()).hexdigest()
            rejected.append((key,payload,r['field'],r['reason'],r['stage']))
        db.executemany('INSERT OR IGNORE INTO rejects VALUES(?,?,?,?,?)',rejected)
        return dict(rows=db.execute('SELECT count(*) FROM quotes').fetchone()[0],
                    inserted=sum(r['business_key'] not in old for r,p,h in changed),
                    updated=sum(r['business_key'] in old for r,p,h in changed),
                    unchanged=len(rows)-len(changed),
                    history=db.execute('SELECT count(*) FROM quote_history').fetchone()[0])


def read_clean():
    data=pd.read_parquet(ROOT/'clean/dataset.parquet')
    result=[]
    for r in data.to_dict('records'):
        r['collected_at']=r['collected_at'].isoformat()
        r['author_birth_year']=None if pd.isna(r['author_birth_year']) else int(r['author_birth_year'])
        r['tags']=list(r['tags'])
        result.append(r)
    return result


def demonstrate(rows,rejects):
    database=ROOT/'db/idempotency_demo.db'
    if database.exists():
        database.unlink()
    results=[dict(run='A',**load(rows,rejects,database))]
    with sqlite3.connect(database) as db:
        before=dict(db.execute('SELECT business_key,updated_at FROM quotes'))
    results.append(dict(run='B',**load(rows,rejects,database)))
    with sqlite3.connect(database) as db:
        after=dict(db.execute('SELECT business_key,updated_at FROM quotes'))
    if before!=after:
        raise AssertionError('updated_at изменился на идентичном повторе')
    changed=copy.deepcopy(rows)
    for r in changed[:2]:
        r['tags']=list(r['tags'])+['demo-change']
    results.append(dict(run='C',**load(changed,rejects,database)))
    if results[1]['updated']!=0 or results[2]['updated']!=2:
        raise AssertionError('Нарушена идемпотентность')
    constraints=[]
    with sqlite3.connect(database) as db:
        key=db.execute('SELECT business_key FROM quotes LIMIT 1').fetchone()[0]
        probes=[
          ('duplicate_key','INSERT INTO quotes SELECT * FROM quotes LIMIT 1',()),
          ('check','UPDATE quotes SET text_length=0 WHERE business_key=?',(key,)),
          ('not_null','UPDATE quotes SET text=NULL WHERE business_key=?',(key,)),
        ]
        for name,sql,args in probes:
            try:
                db.execute(sql,args)
            except sqlite3.IntegrityError as error:
                db.rollback()
                constraints.append(dict(check=name,result='rejected',message=str(error)))
            else:
                db.rollback()
                raise AssertionError(name+' не отклонён')
    (ROOT/'clean/idempotency.json').write_text(json.dumps(
        dict(runs=results,updated_at_preserved=before==after,constraints=constraints),
        ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return results


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--demonstrate',action='store_true')
    args=parser.parse_args()
    rows=read_clean()
    rejects=[json.loads(s) for s in (ROOT/'clean/rejects.jsonl').read_text(encoding='utf-8').splitlines()]
    result=demonstrate(rows,rejects) if args.demonstrate else load(rows,rejects,ROOT/'db/warehouse.db')
    print(json.dumps(result,ensure_ascii=False,indent=2))
