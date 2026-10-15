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


def clean_rows(raw):
    rows=[dict(r,_raw_index=i) for i,r in enumerate(raw)]
    protocol,rejects=[],[]
    def reject(row,stage,field,reason):
        rejects.append(dict(raw_index=row['_raw_index'],stage=stage,field=field,reason=reason,
                            synthetic=bool(row.get('_synthetic')),payload=row))
    def log(step,before,changed=0,note=''):
        protocol.append(dict(step=step,before=before,after=len(rows),changed=changed,
                             removed=before-len(rows),note=note))
    before=len(rows);changed=0
    for row in rows:
        old=json.dumps(row,ensure_ascii=False,sort_keys=True)
        for field in ('text_raw','author_raw','source_id_raw'):
            row[field]=text(row.get(field))
        tags=row.get('tags_raw',[])
        if isinstance(tags,str):
            try:
                tags=json.loads(tags)
            except ValueError:
                tags=[tags]
        row['tags_raw']=[text(t).casefold() for t in tags]
        changed+=old!=json.dumps(row,ensure_ascii=False,sort_keys=True)
    log('1. Нормализация текста',before,changed,'NFKC, NBSP, zero-width, пробелы')
    changed=0
    for row in rows:
        row['source_url']=normalized_url(row.get('_source_url',''))
        changed+=row['source_url']!=row.get('_source_url')
        row['business_key']=quote_key(row['text_raw'],row['author_raw'])
        row['author_key']=author_key(row['author_raw'])
    log('2. Бизнес-ключ и URL',len(rows),len(rows),f'SHA-ключ у всех строк; tracking-URL: {changed}')
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
        missing=[k for k in ('text_raw','author_raw','source_url') if not row.get(k)]
        if missing:
            reject(row,4,','.join(missing),'Отсутствует обязательное поле')
        else:
            kept.append(row)
    rows=kept;log('4. Пропуски',before,note='Текст, автор и URL обязательны; неизвестный год = NULL')
    before=len(rows);dedup={}
    for row in sorted(rows,key=lambda r:r['collected_at']):
        near=(re.sub(r'[\W_]+','',row['author_raw'].casefold()),
              re.sub(r'[\W_]+','',row['text_raw'].casefold()))
        dedup[near]=row
    rows=list(dedup.values());log('5. Полные, ключевые и почти-дубли',before,note='Сохранена самая свежая запись')
    before=len(rows);clean=[]
    for row in rows:
        candidate=dict(business_key=row['business_key'],text=row['text_raw'],author=row['author_raw'],
                       author_key=row['author_key'],tags=list(dict.fromkeys(row['tags_raw'])),
                       source=row['_source'],source_url=row['source_url'],parser_version=row['_parser_version'],
                       collected_at=row['collected_at'],source_record_id=row['source_record_id'],
                       text_length=row['text_length'],author_birth_year=row['author_birth_year'])
        try:
            clean.append(Quote.model_validate(candidate).model_dump(mode='json'))
        except ValidationError as error:
            for issue in error.errors(include_url=False,include_context=False):
                reject(row,6,'.'.join(map(str,issue['loc'])) or 'record',issue['msg'])
    rows=clean;log('6. Бизнес-правила и контракт',before,note='Полный pydantic-контракт; поле и причина в rejects')
    return clean,rejects,protocol
