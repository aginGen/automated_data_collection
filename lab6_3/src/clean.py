import json
import re
import unicodedata
from datetime import datetime,timezone
from urllib.parse import parse_qsl,urlencode,urlsplit,urlunsplit

from pydantic import ValidationError

from .contract import Quote,author_key,quote_key


def text(value):
    if value is None:
        return ''
    value=unicodedata.normalize('NFKC',str(value))
    value=re.sub(r'[\u200b-\u200d\ufeff]','',value.replace('\xa0',' '))
    return ' '.join(value.split())


def normalized_url(value):
    p=urlsplit(text(value))
    query=[(k,v) for k,v in parse_qsl(p.query) if not k.casefold().startswith('utm_')
           and k.casefold() not in ('fbclid','gclid')]
    return urlunsplit((p.scheme.casefold(),p.netloc.casefold(),p.path,urlencode(sorted(query)),''))


def clean_rows(raw, duplicates=None, accepted_indices=None):
    if duplicates is None:
        duplicates=[]
    rows=[dict(r,_raw_index=i) for i,r in enumerate(raw)]
    protocol,rejects=[],[]
    def reject(row,stage,field,reason):
        rejects.append(dict(raw_index=row['_raw_index'],stage=stage,field=field,reason=reason,
                            synthetic=bool(row.get('_synthetic')),payload=row))
    def log(step,before,changed=0,note=''):
        protocol.append(dict(step=step,before=before,after=len(rows),changed=changed,
                             removed=before-len(rows),note=note))
    before=len(rows);changed=0;kept=[]
    for row in rows:
        old=json.dumps(row,ensure_ascii=False,sort_keys=True)
        for field in ('text_raw','author_raw','source_id_raw'):
            row[field]=text(row.get(field))
        tags=row.get('tags_raw',[])
        if isinstance(tags,str):
            try: tags=json.loads(tags)
            except ValueError: tags=[tags]
        if tags is None: tags=[]
        if not isinstance(tags,list) or any(not isinstance(t,str) for t in tags):
            reject(row,1,'tags_raw','Теги должны быть массивом строк или NULL')
            continue
        row['tags_raw']=[text(t).casefold() for t in tags]
        changed+=old!=json.dumps(row,ensure_ascii=False,sort_keys=True)
        kept.append(row)
    rows=kept; log('1. Нормализация текста',before,changed,'NFKC, NBSP, zero-width, пробелы')
    before=len(rows);changed=0;kept=[];url_changed=0
    for row in rows:
        try:
            row['source_url']=normalized_url(row.get('_source_url',''))
        except (ValueError,TypeError) as error:
            reject(row,2,'_source_url',str(error)); continue
        url_changed+=row['source_url']!=row.get('_source_url')
        row['business_key']=quote_key(text(row.get('_source')),row['source_id_raw'])
        row['author_key']=author_key(row['author_raw'])
        changed+=1; kept.append(row)
    rows=kept; log('2. Бизнес-ключ и URL',before,changed,f'SHA(source|source_id); tracking-URL: {url_changed}')
    before=len(rows);kept=[]
    for row in rows:
        try:
            value=datetime.fromisoformat(str(row.get('collected_at_raw',row['_collected_at'])).replace('Z','+00:00'))
            if value.tzinfo is None:
                raise ValueError('Дата без часового пояса')
            row['collected_at']=value.astimezone(timezone.utc).isoformat()
            birth=row.get('author_birth_year_raw')
            row['author_birth_year']=int(birth) if birth not in (None,'') else None
            row['text_length']=len(row['text_raw'])
            row['source_record_id']=str(row['source_id_raw'])
            kept.append(row)
        except (ValueError,TypeError,KeyError) as error:
            reject(row,3,'collected_at / author_birth_year',str(error))
    rows=kept;log('3. Типизация',before,len(rows),'UTC, числовой год, строковый ID; ошибки в rejects')
    before=len(rows);kept=[]
    for row in rows:
        missing=[k for k in ('text_raw','author_raw','source_url','source_id_raw') if not row.get(k)]
        if missing:
            reject(row,4,','.join(missing),'Отсутствует обязательное поле')
        else:
            kept.append(row)
    rows=kept;log('4. Пропуски',before,note='Текст, автор и URL обязательны; неизвестный год = NULL')
    def candidate(row):
        return dict(business_key=row['business_key'],text=row['text_raw'],author=row['author_raw'],
                    author_key=row['author_key'],tags=list(dict.fromkeys(row['tags_raw'])),
                    source=row.get('_source'),source_url=row['source_url'],parser_version=row.get('_parser_version'),
                    collected_at=row['collected_at'],source_record_id=row['source_record_id'],
                    text_length=row['text_length'],author_birth_year=row['author_birth_year'])
    # Step 5 groups candidates only; the contract is evaluated exclusively in step 6.
    before=len(rows); groups={}
    # Union equal source IDs first, then near-text signatures across keys.
    ordered=sorted(rows,key=lambda r:(r['collected_at'],r['_raw_index']))
    parent=list(range(len(ordered)))
    def find(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]]; i=parent[i]
        return i
    def union(i,j):
        a,b=find(i),find(j)
        if a!=b: parent[b]=a
    by_key={}
    for i,row in enumerate(ordered):
        key=row['business_key']
        if key in by_key: union(i,by_key[key])
        else: by_key[key]=i
    by_near={}
    for i,row in enumerate(ordered):
        near=(re.sub(r'[\W_]+','',row['author_raw'].casefold()),
              re.sub(r'[\W_]+','',row['text_raw'].casefold()))
        if near in by_near: union(i,by_near[near])
        else: by_near[near]=i
    for i,row in enumerate(ordered): groups.setdefault(find(i),[]).append(row)
    rows=[group[-1] for group in groups.values()]
    log('5. Полные, ключевые и почти-дубли',before,note='Сформированы группы; альтернативы отложены до контракта')
    before=len(rows);clean=[]; fallback=0; invalid_alternatives=0
    for group in groups.values():
        valid=[]; invalid=[]
        for row in reversed(group):
            try:
                valid.append((row,Quote.model_validate(candidate(row)).model_dump(mode='json')))
            except ValidationError as error:
                invalid.append(row)
                for issue in error.errors(include_url=False,include_context=False):
                    reject(row,6,'.'.join(map(str,issue['loc'])) or 'record',issue['msg'])
        if valid:
            winner,result=valid[0]; clean.append(result)
            if accepted_indices is not None: accepted_indices.append(winner['_raw_index'])
            if winner is not group[-1]: fallback+=1
        else:
            winner=group[-1]
        for row in group:
            if row is winner: continue
            invalid_row=any(row is r for r in invalid)
            if invalid_row: invalid_alternatives+=1
            duplicates.append(dict(raw_index=row['_raw_index'],winner_raw_index=winner['_raw_index'],
                status='rejected' if invalid_row else 'duplicate',
                reason=('invalid_duplicate' if invalid_row else
                        'exact' if all(row.get(k)==winner.get(k) for k in ('text_raw','author_raw','tags_raw','source_id_raw','_source','source_url','collected_at')) else
                        'business_key' if row['business_key']==winner['business_key'] else 'near_duplicate'),payload=row))
    rows=clean;log('6. Бизнес-правила и контракт',before,changed=len(clean),note=f'Контракт всех кандидатов; fallback={fallback}; невалидных альтернатив={invalid_alternatives}; всего rejects={len({r["raw_index"] for r in rejects})}')
    return clean,rejects,protocol
