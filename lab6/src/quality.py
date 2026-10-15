from collections import Counter
from datetime import datetime,timezone
from statistics import median

from pydantic import ValidationError

from .clean import clean_rows
from .contract import Quote


def passes_contract(row):
    try:
        Quote.model_validate(row)
        return True
    except ValidationError:
        return False


def quality(raw,clean,rejects,previous_count=None):
    count=len(clean)
    mandatory=('business_key','text','author','author_key','source','source_url','collected_at')
    complete=sum(all(r.get(k) not in (None,'') for k in mandatory) for r in clean)/max(count,1)
    optional=sum(r['author_birth_year'] is not None for r in clean)/max(count,1)
    rejected={r['raw_index'] for r in rejects}
    valid_raw=sum(bool(clean_rows([row])[0]) for row in raw)
    baseline=count if previous_count is None else previous_count
    days=median((datetime.now(timezone.utc)-datetime.fromisoformat(r['collected_at'].replace('Z','+00:00'))).total_seconds()/86400
                for r in clean) if clean else float('inf')
    values=[
      ('mandatory_completeness',complete,1.0,0.99,'min','Обязательные поля нужны для загрузки'),
      ('optional_completeness',optional,0.10,0.05,'min','Год рождения доступен у части HTML-авторов'),
      ('unique_keys',len({r['business_key'] for r in clean})/max(count,1),1.0,0.99,'min','Уникальный бизнес-ключ'),
      ('validity',valid_raw/max(len(raw),1),0.90,0.80,'min','До 10% явно внесённых дефектов'),
      ('reject_share',len(rejected)/max(len(raw),1),0.10,0.20,'max','До 10% учебной отбраковки'),
      ('business_consistency',sum(passes_contract(r) for r in clean)/max(count,1),1.0,0.99,'min','Полный контракт и согласованность полей'),
      ('median_age_days',days,30.0,60.0,'max','Для учебных метаданных допустим возраст до месяца'),
      ('volume_change',abs(count-baseline)/max(baseline,1),0.10,0.20,'max','Изменение объёма до 10%'),
    ]
    rows=[]
    for name,value,green,yellow,direction,reason in values:
        if direction=='min':
            status='green' if value>=green else ('yellow' if value>=yellow else 'red')
        else:
            status='green' if value<=green else ('yellow' if value<=yellow else 'red')
        rows.append(dict(metric=name,value=round(value,6),green=green,yellow=yellow,
                         direction=direction,status=status,reason=reason))
    verdict='red' if any(r['status']=='red' for r in rows) else (
        'yellow' if any(r['status']=='yellow' for r in rows) else 'green')
    return dict(rows=count,raw_rows=len(raw),contract_valid_raw=valid_raw,rejected_rows=len(rejected),
                reject_reasons=dict(Counter(r['reason'] for r in rejects)),metrics=rows,verdict=verdict)


def require_mart(report):
    failed=[r['metric'] for r in report['metrics'] if r['status']=='red']
    if failed:
        raise RuntimeError('Mart не обновлён: красные метрики: '+', '.join(failed))
