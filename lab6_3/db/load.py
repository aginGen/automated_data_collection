from contextlib import closing
import argparse
import copy
import hashlib
import json
import sqlite3
import tempfile
from datetime import datetime,timezone
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]


def load(rows,rejects,database):
    rows=[dict(r,collected_at=datetime.fromisoformat(r['collected_at'].replace('Z','+00:00')).astimezone(timezone.utc).isoformat()) for r in rows]
    now=datetime.now(timezone.utc).isoformat()
    Path(database).parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(database)) as db, db:
        db.executescript((ROOT/'db/schema.sql').read_text(encoding='utf-8'))
        authors={}
        for r in rows:
            previous=authors.get(r['author_key'])
            birth=r['author_birth_year'] if r['author_birth_year'] is not None else (previous[2] if previous else None)
            authors[r['author_key']]=(r['author_key'],r['author'],birth)
        db.executemany('INSERT INTO authors VALUES(?,?,?) ON CONFLICT(author_key) DO UPDATE SET '
                       'name=excluded.name,birth_year=COALESCE(excluded.birth_year,authors.birth_year)',
                       list(authors.values()))
        old={key:(digest,active) for key,digest,active in db.execute('SELECT business_key,payload_hash,is_active FROM quotes')}
        incoming={r['business_key'] for r in rows}
        if len(incoming)!=len(rows): raise ValueError('Повторный бизнес-ключ во входном снапшоте')
        deactivated=[key for key,(digest,active) in old.items() if active and key not in incoming]
        db.executemany('UPDATE quotes SET is_active=0,updated_at=? WHERE business_key=?',[(now,key) for key in deactivated])
        changed=[]
        for r in rows:
            payload=json.dumps(r,ensure_ascii=False,sort_keys=True)
            digest=hashlib.sha256(payload.encode()).hexdigest()
            previous=old.get(r['business_key'])
            if previous is None or previous[0]!=digest or not previous[1]:
                changed.append((r,payload,digest))
        sql="""INSERT INTO quotes(business_key,text,author_key,source,source_url,parser_version,source_record_id,collected_at,updated_at,text_length,tags_json,payload_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(business_key) DO UPDATE SET text=excluded.text,
        author_key=excluded.author_key,source=excluded.source,source_url=excluded.source_url,
        parser_version=excluded.parser_version,source_record_id=excluded.source_record_id,
        collected_at=excluded.collected_at,updated_at=excluded.updated_at,
        text_length=excluded.text_length,tags_json=excluded.tags_json,payload_hash=excluded.payload_hash,is_active=1
        WHERE quotes.payload_hash<>excluded.payload_hash OR quotes.is_active=0"""
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
        return dict(rows=db.execute('SELECT count(*) FROM quotes WHERE is_active=1').fetchone()[0],
                    total_rows=db.execute('SELECT count(*) FROM quotes').fetchone()[0],
                    inactive=db.execute('SELECT count(*) FROM quotes WHERE is_active=0').fetchone()[0],
                    deactivated=len(deactivated),
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
    # A new uniquely named database never removes an existing user's database.
    with tempfile.NamedTemporaryFile(prefix='idempotency_demo_',suffix='.db',delete=False) as f:
        database=Path(f.name)
    results=[dict(run='A',**load(rows,rejects,database))]
    with closing(sqlite3.connect(database)) as db, db:
        before=dict(db.execute('SELECT business_key,updated_at FROM quotes'))
    results.append(dict(run='B',**load(rows,rejects,database)))
    with closing(sqlite3.connect(database)) as db, db:
        after=dict(db.execute('SELECT business_key,updated_at FROM quotes'))
    if before!=after:
        raise AssertionError('updated_at изменился на идентичном повторе')
    changed=copy.deepcopy(rows)
    for r in changed[:2]:
        r['tags']=list(r['tags'])+['demo-change']
    results.append(dict(run='C',**load(changed,rejects,database)))
    with closing(sqlite3.connect(database)) as db, db:
        after_c=dict(db.execute('SELECT business_key,updated_at FROM quotes'))
    changed_keys=[k for k in before if before[k]!=after_c[k]]
    if len(changed_keys)!=2 or results[2]['history']-results[1]['history']!=2:
        raise AssertionError('Ожидалось ровно два изменения и две записи истории')
    if results[1]['updated']!=0 or results[2]['updated']!=2:
        raise AssertionError('Нарушена идемпотентность')
    constraints=[]
    with closing(sqlite3.connect(database)) as db, db:
        key=db.execute('SELECT business_key FROM quotes LIMIT 1').fetchone()[0]
        probes=[
          ('duplicate_key',"INSERT INTO quotes SELECT business_key,text,author_key,source,source_url,parser_version,source_record_id || '-duplicate',collected_at,updated_at,text_length,tags_json,payload_hash,is_active FROM quotes LIMIT 1",()),
          ('check',"INSERT INTO quotes SELECT ?,text,author_key,source,source_url,parser_version,source_record_id || '-check',collected_at,updated_at,0,tags_json,payload_hash,is_active FROM quotes LIMIT 1",('f'*64,)),
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
        dict(database=str(database),runs=results,updated_at_preserved=before==after,changed_keys=changed_keys,constraints=constraints),
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
