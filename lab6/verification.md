# Проверка лабораторной 6

Проверены технические этапы работы. HTML и страницы авторов взяты из пятой лабораторной; DummyJSON — дополнительный API для объёма от 300 цитат. Это явно указано в отчёте.

| Что проверено | Результат | Где смотреть |
|---|---|---|
| Вариант и источник | Цитаты/авторы; HTML и страницы авторов из5, новый дополнительный API DummyJSON. API добавлен для минимального объёма | report.md: 1–2; README.md |
| Объём и учебные дефекты | 452 входных, 32 synthetic (7,08%), 414 чистых; нет набора объёма копированием строк | raw; clean/rebuild_summary.json |
| Raw и происхождение | JSONL, пять служебных полей, сырые поля/HTML; append-only manifest; Git сохраняет байты | raw/manifest.json; .gitattributes |
| Офлайн-пересборка | Работает без сайтов; raw не изменился, повтор warehouse обновил0 строк | src/rebuild.py; clean/rebuild_summary.json |
| Форматы | Один набор: размер/полное и выборочное чтение/типы UTC и000100; медиана7 чтений | clean/format_benchmark.csv; format_types.json; report.md: 3 |
| Очистка | Шесть шагов по порядку; до/после/изменено/удалено/примечание; NULL вместо выдуманных значений | clean/cleaning_protocol.csv; report.md: 4 |
| Контракт | 7+ предметных/согласующих правил, 3 field_validator и model_validator; семь битых случаев с сообщениями | src/contract.py; clean/contract_examples.json |
| БД | PK/FK/NOT NULL/CHECK/UNIQUE/индексы и служебные поля; схема связей и их назначение | db/schema.sql; report.md: 6 |
| UPSERT и история | Пакетная загрузка; A414/0, B0/0, C0/2; история414/414/416, updated_at повтором не меняется | db/load.py; clean/idempotency.json |
| Ограничения | CHECK, повторный ключ и NOT NULL действительно отклонены | clean/idempotency.json |
| Качество | 8 метрик; контракт428/452 до удаления дублей; полный контракт проверен снова; пороги/причины/вердикт | src/quality.py; clean/quality.json |
| Красный запрет | force-red: код2, raw и mart сохраняются; нулевая предыдущая выборка тоже учитывается | src/quality.py; src/rebuild.py |
| Mart | 3 SQL/Parquet-представления, партиции, чтение одной, 2 графика; два повтора по414 без дублей | mart; quality_report.ipynb |
| n8n | 39 вход → 34 чистых +3 брака +2 дубля; нормализация3+, IF/Remove Duplicates/CSV/расписание | nocode; report.md: 9–10 |
| Ограничения n8n | Отдельная колонка; CSV без UPSERT/истории, полного контракта/near-дублей/mart | report.md: 9 |
| Право | Состав и потенциальные ПД, минимизация, место/срок, 152-ФЗ/GDPR и ссылки | report.md: 11 |

Отчёт: [PDF](report.pdf), [исходник](report.md). Показ: [defense.md](defense.md).
