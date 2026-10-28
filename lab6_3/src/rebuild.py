from contextlib import closing
import argparse
import copy
import hashlib
import json
import sqlite3
import statistics
import time
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from pydantic import ValidationError

from db.load import load
from .clean import clean_rows
from .contract import Quote
from .quality import quality,require_mart


ROOT=Path(__file__).resolve().parents[1]


def write_json(path,value):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')


def verify_raw():
    manifest=json.loads((ROOT/'raw/manifest.json').read_text(encoding='utf-8'))
    hashes={}
    for filename,entry in manifest.items():
        body=(ROOT/'raw'/filename).read_bytes()
        if len(body)<entry['original_bytes'] or hashlib.sha256(body[:entry['original_bytes']]).hexdigest()!=entry['sha256']:
            raise RuntimeError('Изменены прежние строки raw: '+filename)
        hashes[filename]=hashlib.sha256(body).hexdigest()
    rolling=ROOT/'clean/raw_prefix_manifest.json'
    prior=json.loads(rolling.read_text(encoding='utf8')) if rolling.exists() else {}
    for filename,entry in prior.items():
        file=ROOT/'raw'/filename
        if not file.exists(): raise RuntimeError('Удалён файл raw: '+filename)
        body=file.read_bytes()
        if len(body)<entry['bytes'] or hashlib.sha256(body[:entry['bytes']]).hexdigest()!=entry['sha256']:
            raise RuntimeError('Изменён ранее прочитанный префикс raw: '+filename)
    for file in sorted((ROOT/'raw').glob('*.jsonl')):
        body=file.read_bytes()
        if body and not body.endswith(b'\n'): raise RuntimeError('Неполная строка raw: '+file.name)
        hashes[file.name]=hashlib.sha256(body).hexdigest()
    return hashes


def benchmark(frame):
    directory=ROOT/'clean/formats'
    directory.mkdir(parents=True,exist_ok=True)
    encoded=frame.copy()
    encoded['tags']=encoded['tags'].map(lambda v:json.dumps(v,ensure_ascii=False))
    paths={'CSV':directory/'dataset.csv','JSONL':directory/'dataset.jsonl','Parquet':directory/'dataset.parquet'}
    encoded.to_csv(paths['CSV'],index=False,encoding='utf-8-sig')
    encoded.to_json(paths['JSONL'],orient='records',lines=True,date_format='iso',date_unit='us',force_ascii=False)
    encoded.to_parquet(paths['Parquet'],index=False)
    columns=['source_record_id','collected_at','text_length']
    readers={
      'CSV':lambda subset:pd.read_csv(paths['CSV'],usecols=columns if subset else None),
      'JSONL':lambda subset:pd.read_json(paths['JSONL'],lines=True)[columns] if subset else pd.read_json(paths['JSONL'],lines=True),
      'Parquet':lambda subset:pd.read_parquet(paths['Parquet'],columns=columns if subset else None),
    }
    rows=[]
    types={}
    for name,reader in readers.items():
        times=[]
        for subset in (False,True):
            samples=[]
            for _ in range(7):
                start=time.perf_counter()
                restored=reader(subset)
                samples.append((time.perf_counter()-start)*1000)
            times.append(statistics.median(samples))
        restored=reader(False)
        rows.append(dict(format=name,bytes=paths[name].stat().st_size,read_all_ms=round(times[0],4),
                         read_three_ms=round(times[1],4),date_dtype=str(restored['collected_at'].dtype),
                         id_dtype=str(restored['source_record_id'].dtype),
                         id_example=str(restored['source_record_id'].iloc[0])))
        types[name]={column:str(dtype) for column,dtype in restored.dtypes.items()}
    pd.DataFrame(rows).to_csv(ROOT/'clean/format_benchmark.csv',index=False)
    write_json(ROOT/'clean/format_types.json',types)
    return rows


def contract_examples(clean):
    base=clean[0]
    cases=[
      ('Пустой текст',{'text':''}),
      ('Короткое имя',{'author':'X'}),
      ('Неверный тег',{'tags':['Bad Tag!']}),
      ('Дата без зоны',{'collected_at':'2020-01-01T00:00:00'}),
      ('Неверный ключ',{'business_key':'f'*64}),
      ('Неверная длина',{'text_length':0}),
      ('Неверный источник URL',{'source_url':'https://example.org/quote'}),
    ]
    result=[]
    for name,change in cases:
        try:
            Quote.model_validate(dict(base,**change))
        except ValidationError as error:
            result.append(dict(check=name,result='rejected',message=error.errors(include_url=False,include_context=False)[0]['msg']))
        else:
            raise AssertionError('Битая запись принята: '+name)
    write_json(ROOT/'clean/contract_examples.json',result)
    return result


def build_mart(frame):
    directory=ROOT/'mart/views'
    directory.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(ROOT/'db/warehouse.db')) as db, db:
        for view in ('quotes_by_author','quotes_by_source','popular_tags'):
            pd.read_sql_query('SELECT * FROM '+view,db).to_parquet(directory/(view+'.parquet'),index=False)
    snapshot=frame.assign(dt=frame['collected_at'].dt.strftime('%Y-%m-%d'))
    snapshot_root=(ROOT/'mart/snapshots').resolve()
    if snapshot_root.parent != (ROOT/'mart').resolve():
        raise RuntimeError('Неверный путь снапшотов')
    if snapshot_root.exists() and any(not p.resolve().is_relative_to(snapshot_root) for p in snapshot_root.iterdir()):
        raise RuntimeError('Партиция выходит за каталог снапшотов')
    snapshot.to_parquet(snapshot_root,partition_cols=['dt'],index=False,
                        existing_data_behavior='delete_matching',basename_template='part-{i}.parquet')
    parts=sorted(p.name for p in (ROOT/'mart/snapshots').iterdir() if p.is_dir())
    one=pd.read_parquet(ROOT/'mart/snapshots',filters=[('dt','=',parts[0].split('=')[1])])
    write_json(ROOT/'mart/partition_read.json',dict(partitions=parts,selected=parts[0],rows=len(one)))
    by_source=frame.groupby('source').size()
    tags=pd.read_parquet(directory/'popular_tags.parquet').head(10)
    fig,axes=plt.subplots(1,2,figsize=(10,4.2))
    by_source.plot.bar(ax=axes[0],color=['#355c7d','#70976c'],rot=0)
    axes[0].set(title='Цитаты по источникам',xlabel='Источник',ylabel='Цитат')
    tags.sort_values('quotes').plot.barh(x='tag',y='quotes',ax=axes[1],legend=False,color='#355c7d')
    axes[1].set(title='Частые теги',xlabel='Цитат',ylabel='Тег')
    fig.tight_layout()
    (ROOT/'figures').mkdir(exist_ok=True)
    fig.savefig(ROOT/'figures/mart.png',dpi=150)
    plt.close(fig)
    fig,ax=plt.subplots(figsize=(7,4)); frame.groupby(frame['collected_at'].dt.strftime('%Y-%m-%d')).size().plot.bar(ax=ax,color='#70976c',rot=30); ax.set(title='Цитаты по дате сбора',xlabel='Дата сбора UTC',ylabel='Цитат'); fig.tight_layout(); fig.savefig(ROOT/'figures/collection_timeline.png',dpi=150); plt.close(fig)
    fig,ax=plt.subplots(figsize=(7,4)); frame['text_length'].plot.hist(ax=ax,bins=25,color='#355c7d'); ax.set(title='Распределение длины цитат',xlabel='Символов',ylabel='Цитат'); fig.tight_layout(); fig.savefig(ROOT/'figures/length_distribution.png',dpi=150); plt.close(fig)


def rebuild(force_red=False):
    start=time.perf_counter()
    before=verify_raw()
    raw=[]
    for file in sorted((ROOT/'raw').glob('*.jsonl')):
        raw.extend(json.loads(line) for line in file.read_text(encoding='utf-8').splitlines() if line.strip())
    duplicates=[]; accepted=[]
    clean,rejects,protocol=clean_rows(raw,duplicates,accepted)
    previous_path=ROOT/'clean/quality.json'
    previous=json.loads(previous_path.read_text(encoding='utf-8'))['rows'] if previous_path.exists() else None
    outcome=quality(raw,clean,rejects,previous)
    if force_red:
        simulated=copy.deepcopy(outcome)
        simulated['metrics'][0]['status']='red'
        require_mart(simulated)
    require_mart(outcome)
    if len(clean)<300:
        raise RuntimeError('В чистом слое меньше 300 уникальных записей')
    (ROOT/'clean').mkdir(exist_ok=True)
    frame=pd.DataFrame(clean)
    frame['collected_at']=pd.to_datetime(frame['collected_at'],utc=True)
    frame['author_birth_year']=pd.array(frame['author_birth_year'],dtype='Int64')
    frame['text_length']=pd.array(frame['text_length'],dtype='Int64')
    frame['source_record_id']=frame['source_record_id'].astype('string')
    frame.to_parquet(ROOT/'clean/dataset.parquet',index=False)
    authors=frame[['author_key','author','author_birth_year']].sort_values('author_birth_year',na_position='last').drop_duplicates('author_key')
    authors.to_parquet(ROOT/'clean/authors.parquet',index=False)
    tag_rows=[dict(business_key=r['business_key'],tag=tag) for r in clean for tag in r['tags']]
    pd.DataFrame(tag_rows).to_parquet(ROOT/'clean/quote_tags.parquet',index=False)
    (ROOT/'clean/rejects.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False,default=str)+'\n' for r in rejects),encoding='utf-8')
    (ROOT/'clean/duplicates.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False,default=str)+'\n' for r in duplicates),encoding='utf-8')
    rejected_indices={r['raw_index'] for r in rejects}
    accepted_indices=set(accepted)
    duplicate_indices={r['raw_index'] for r in duplicates if r['status']=='duplicate'}
    if accepted_indices & rejected_indices or accepted_indices & duplicate_indices or rejected_indices & duplicate_indices or accepted_indices | rejected_indices | duplicate_indices != set(range(len(raw))):
        raise AssertionError('Неполное или пересекающееся распределение raw')
    disposition=[dict(raw_index=i,status=('accepted' if i in accepted_indices else 'rejected' if i in rejected_indices else 'duplicate')) for i in range(len(raw))]
    write_json(ROOT/'clean/raw_disposition.json',dict(counts=dict(accepted=len(accepted_indices),rejected=len(rejected_indices),duplicate=len(duplicate_indices)),rows=disposition))
    write_json(ROOT/'clean/cleaning_protocol.json',protocol)
    pd.DataFrame(protocol).to_csv(ROOT/'clean/cleaning_protocol.csv',index=False,encoding='utf-8-sig')
    write_json(ROOT/'clean/quality.json',outcome)
    formats=benchmark(frame)
    examples=contract_examples(clean)
    loaded=load(clean,rejects,ROOT/'db/warehouse.db')
    build_mart(frame)
    after=verify_raw()
    if before!=after:
        raise AssertionError('Raw изменился во время пересборки')
    write_json(ROOT/'clean/raw_prefix_manifest.json',{file.name:dict(bytes=file.stat().st_size,sha256=before[file.name]) for file in (ROOT/'raw').glob('*.jsonl')})
    summary=dict(duplicates=len(duplicates),raw_rows=len(raw),clean_rows=len(clean),authors=len(authors),tag_links=len(tag_rows),
                 rejected_rows=outcome['rejected_rows'],quality=outcome['verdict'],raw_unchanged=True,
                 load=loaded,duration_s=round(time.perf_counter()-start,4))
    write_json(ROOT/'clean/rebuild_summary.json',summary)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--force-red',action='store_true')
    args=parser.parse_args()
    try:
        print(json.dumps(rebuild(args.force_red),ensure_ascii=False,indent=2))
    except RuntimeError as error:
        print(str(error))
        raise SystemExit(2)
