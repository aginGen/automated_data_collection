# Лабораторная работа 5 Промышленный краулинг

**ПМИ-2-2025, вариант 3.**

Собраны 100 уникальных цитат с десяти страниц Quotes to Scrape и сведения 50 авторов. Дополнительный обход тегов выполнен по подходу [LaintAge/web-scrapers](https://github.com/LaintAge/web-scrapers/tree/main/lb5): 190 связей «цитата–тег» для 69 цитат и 99 тегов. В n8n реально выполнен сбор первых 30 цитат с данными авторов; результат совпадает с Scrapy.

На учебном сайте всего 100 уникальных цитат. Теги не создают новые цитаты: 190 связей хранятся отдельно и не прибавляются к числу уникальных записей. Общий минимум 300 из ТЗ здесь не достигнут; это ограничение указано в отчёте. Предохранитель CLOSESPIDER_ITEMCOUNT=300 включён у основного паука, у тегового предел 10 000 связей; оба ограничены временем 900 с. Дополнительные источники не используются.

Готовый отчёт: [PDF, 5 страниц](report.pdf) и [Markdown](report.md). Дата сохранённого среза — 28 октября 2026 года; результаты и время следующего сетевого запуска могут отличаться.

## Состав папки

```text
lab5_3/
├── scrapy.cfg
├── quotes_crawler/
│   ├── items.py                 # QuoteItem, схема полей
│   ├── pipelines.py             # четыре звена основного пайплайна
│   ├── tag_pipelines.py         # обработка связей цитата–тег
│   ├── settings.py              # вежливость и предохранители
│   └── spiders/
│       ├── quotes.py            # каталог → авторы, вариант 3
│       └── tags.py              # расширенный обход по тегам
├── data/
│   ├── crawl.db                 # quotes=100, quote_tags=190
│   ├── items.jsonl              # 100 уникальных цитат, Feed Exports
│   ├── items_quotes.jsonl       # та же основная выборка
│   ├── items_tags.jsonl         # 190 связей с контекстом
│   ├── stats_*.json             # отдельная статистика каждого опыта
│   ├── cache_cold.db            # независимый полный прогон
│   ├── cache_warm.db            # повтор с HTTP-кэшем
│   ├── job_resume.db            # 34 + 66 = 100 после JOBDIR
│   ├── benchmark30.db           # тот же срез, что у n8n
│   ├── job_audit.json           # URL до/после остановки
│   ├── tag_coverage.json        # 190 из 232 связей основного каталога
│   └── replay_relations.json    # повтор: 0 вставок, 190 пропусков
├── jobstate/                   # сохранённые очереди и отпечатки
├── quality/
│   ├── quality_report.ipynb     # выполненный анализ и графики
│   ├── analyze.py               # пересчёт качества без сетевых запросов
│   ├── checks/                 # регрессионные проверки и повтор записи
│   ├── reproduce.ps1           # повтор опытов
│   ├── smoke_check.py           # сравнение независимых прогонов
│   ├── check_smoke.py           # проверки границ порогов
│   ├── current.json            # метрики итогового набора
│   ├── previous.json           # независимый снимок холодного опыта
│   ├── completeness.csv
│   └── figures/quotes_aggregates.png
├── nocode/
│   ├── workflow.json
│   ├── screenshot_*.png
│   ├── nocode_result.csv
│   ├── metrics.json
│   ├── execution_summary.json
│   ├── error_test.json
│   ├── notification_server.py   # локальная панель уведомлений
│   ├── notifications.jsonl
│   └── README.md
├── report.md
├── report.pdf
├── requirements.txt
└── README.md
```

Вспомогательные `.db`, `.jsonl` и журналы в data относятся к подписанным экспериментам; они не объединяются в итоговый объём. В `jobstate` хранятся сериализованные объекты Scrapy: использовать только собственные доверенные каталоги состояния и ту же версию Scrapy.

## Установка и запуск с нуля

Команды PowerShell выполняются **из этой папки**, а не из корня соседнего .NET-решения. Проверенная версия Scrapy зафиксирована в requirements.txt.

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONPATH = '.'
.\.venv\Scripts\python.exe -m scrapy list
```

Новый прогон сохраняется под отдельными именами, чтобы исходный срез оставался доступен:

```powershell
$run = Get-Date -Format 'yyyyMMdd_HHmmss'
.\.venv\Scripts\python.exe -m scrapy crawl quotes -a "run_id=${run}_quotes" -s "DATABASE_PATH=data/${run}.db" -s "JOBDIR=jobstate/${run}_quotes" -O "data/${run}_quotes.jsonl"
.\.venv\Scripts\python.exe -m scrapy crawl tags -a "run_id=${run}_tags" -s "DATABASE_PATH=data/${run}.db" -s "JOBDIR=jobstate/${run}_tags" -O "data/${run}_tags.jsonl"
.\.venv\Scripts\python.exe quality/analyze.py --db "data/${run}.db" --output "quality/${run}"
```

Для нового полного среза используйте **новую SQLite**, а не накопленную таблицу прошлого прогона: UPSERT не удаляет записи, исчезнувшие с сайта. Пауки запускаются последовательно в одну БД. Теговый паук сохраняет происхождение ранее собранных цитат через INSERT OR IGNORE. При запуске только tags без основного каталога будут доступны 69 цитат выбранного участка графа, а не все 100.

## Проверки и анализ сохранённого среза

```powershell
.\.venv\Scripts\python.exe -m quality.checks.test_pipelines
.\.venv\Scripts\python.exe -m quality.checks.verify_crawl
.\.venv\Scripts\python.exe quality/analyze.py
.\.venv\Scripts\python.exe quality/check_smoke.py
.\.venv\Scripts\python.exe quality/smoke_check.py quality/previous.json quality/quotes_snapshot.json
.\.venv\Scripts\jupyter.exe notebook quality/quality_report.ipynb
```

В ноутбуке выбрать Python окружения `.venv` и выполнить все ячейки. Для запуска без интерфейса:

```powershell
.\.venv\Scripts\python.exe -m jupyter nbconvert --to notebook --execute --inplace quality/quality_report.ipynb
```

Ноутбук читает только локальные файлы. Он проверяет уникальность, даты, 10 страниц каталога, связи с существующими цитатами, рассчитывает полноту всех полей, три агрегата, статистику HTTP, строит график и сравнивает 30 цитат и биографические поля с CSV n8n. `previous.json` вычислен из отдельной `cache_cold.db`, текущий снимок — из `crawl.db`.

Smoke-check возвращает 0 при отсутствии деградации, 1 при падении объёма более 20% или доле пустых обязательных ячеек более 5%, 2 при ошибке входных данных или несовместимых окнах сбора. Точные границы 20% и 5% допустимы. `smoke_demonstration.json` содержит **синтетические** проверки, а не историю ошибок сайта. Пустой список тегов допустим; обязательные скалярные поля проверяются отдельно.

## JOBDIR и HTTP-кэш

```powershell
powershell -ExecutionPolicy Bypass -File quality/reproduce.ps1 -Python '.\.venv\Scripts\python.exe'
```

Скрипт создаёт отдельные результаты холодного и тёплого кэша, остановки/продолжения JOBDIR, парного замера 30 цитат и обхода тегов. Имена содержат время; прежние результаты не перезаписываются. Проверяйте успешное завершение каждого процесса.

В сохранённом опыте cache_cold получил 100 цитат за 27,589 с, cache_warm — за 3,037 с с 61 попаданием в кэш. JOBDIR остановился на 34 цитатах при лимите 20 и добавил 66 после продолжения; превышение порога вызвано уже запущенными обработчиками. Отпечатки дали `dupefilter/filtered=1`; пересечение посещённых URL до и после остановки равно нулю. Время и байты тёплого кэша не обозначают новый сетевой трафик.

Для отдельной демонстрации используйте **один** JOBDIR только для одной пары остановка/продолжение. Новый независимый прогон требует нового каталога. Повтор уже завершённого JOBDIR может не обработать ни одной страницы. Состояние восстановимо после штатного закрытия, сохранность при повреждении файлов не гарантируется.

## Запуск n8n

Подробные параметры и подтверждение выполнения — в [nocode/README.md](nocode/README.md). Сначала из корня лабораторной работы запустите приёмник в отдельном PowerShell:

```powershell
.\.venv\Scripts\python.exe .\nocode\notification_server.py
```

Откройте `http://127.0.0.1:5686/` и оставьте панель открытой: полученное сообщение появляется в браузере и сохраняется в JSONL. Это локальная панель, не системное push-уведомление. При выключенном приёмнике n8n явно сообщает о недоставке. Затем во втором PowerShell можно запустить отдельную локальную установку n8n:

```powershell
npm.cmd install --prefix .n8n-runtime n8n@1.121.3
$env:N8N_USER_FOLDER = Join-Path $env:TEMP 'lab5-n8n-isolated'
$env:N8N_LISTEN_ADDRESS = '127.0.0.1'
$env:N8N_PORT = '5685'
$env:N8N_DIAGNOSTICS_ENABLED = 'false'
$env:NODE_FUNCTION_ALLOW_BUILTIN = 'crypto'
$env:NO_PROXY = 'localhost,127.0.0.1,quotes.toscrape.com'
$env:GENERIC_TIMEZONE = 'Asia/Yekaterinburg'
$env:N8N_RESTRICT_FILE_ACCESS_TO = (Get-Location).Path
.\.n8n-runtime\node_modules\.bin\n8n.cmd import:workflow --input=nocode/workflow.json
.\.n8n-runtime\node_modules\.bin\n8n.cmd start
```

Открыть `http://localhost:5685`, завершить первоначальную локальную настройку, открыть импортированный workflow и выполнить Manual start. Запускать процесс из корня этой лабораторной: путь CSV относительный. Schedule Trigger настроен ежедневно на 08:00 Asia/Yekaterinburg и заработает после активации workflow. Сохранённый CSV относится к успешному ручному выполнению #8; тест #9 проверил доставку уведомления, а #10 — остановку при недоступном приёмнике. Эти ошибки не заменяли успешный CSV.

Результат: 30 строк, по 10 со страниц 1–3; 33,100 с. SHA-256 CSV указан в `metrics.json`. После неуспешного запуска предыдущий CSV может остаться на диске: проверяйте статус выполнения. Метрики n8n описывают успешно обработанные ответы и длины HTML, а не непосредственное измерение всех сетевых попыток; отличие от Scrapy объяснено в отчёте.

## Отчёт и воспроизводимость

`report.md` содержит все разделы, перечисленные в ТЗ: вариант и карту источника, архитектуру, пауков, пайплайны, настройки, JOBDIR/кэш, качество, n8n, сравнение, три сценария, редизайн, smoke-check, правовой раздел и источники. `report.pdf` свёрстан на пяти страницах и проверен визуально. При правке Markdown PDF можно пересобрать:

```powershell
.\.venv\Scripts\python.exe quality/render_report.py
```

Рендерер использует ReportLab и шрифты Times из `C:/Windows/Fonts`. Измерения в отчёте относятся к сохранённым запускам 28 октября; при обновлении среза нужно пересчитать таблицы и заново проверить PDF. Исправления валидации, ссылок и счётчика SQLite проверяются регрессионными тестами; `data/replay_relations.json` подтверждает повторную запись всех связей без ложных вставок.
