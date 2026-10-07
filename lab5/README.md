# Лабораторная 5. Краулинг с Scrapy и n8n

Вариант 3: [Quotes to Scrape](https://quotes.toscrape.com/).
На сайте 100 цитат. Для объёма от 300 записей добавлен
[Books to Scrape](https://books.toscrape.com/): собраны ещё 304 книги.

## Запуск

Команды выполняются из папки `lab5`. Нужен Python 3.10 или новее.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m scrapy crawl quotes -a run_id=quotes_new -s JOBDIR=jobstate/new_quotes -O data/quotes_new.jsonl
.\.venv\Scripts\python.exe -m scrapy crawl books -a run_id=books_new -s JOBDIR=jobstate/new_books -O data/books_new.jsonl
.\.venv\Scripts\python.exe quality/analyze.py
```

Данные сохраняются в `data/crawl.db`. Повторная запись по тому же ключу обновляет строку.
Для нового обхода нужен новый `JOBDIR`; для продолжения — прежний.
У каждого паука должен быть свой каталог состояния.

## Остановка и продолжение

```powershell
.\.venv\Scripts\python.exe -m scrapy crawl quotes -a run_id=pause -s JOBDIR=jobstate/demo -s CLOSESPIDER_ITEMCOUNT=35 -O data/pause.jsonl
.\.venv\Scripts\python.exe -m scrapy crawl quotes -a run_id=resume -s JOBDIR=jobstate/demo -s CLOSESPIDER_ITEMCOUNT=300 -O data/resume.jsonl
```

Первый запуск останавливается после 35 цитат, второй продолжает ту же очередь.
Используйте новый каталог `jobstate/demo`: в сохранённых каталогах лежат состояния выполненных обходов.

## HTTP-кэш

```powershell
.\.venv\Scripts\python.exe -m scrapy crawl quotes -a run_id=cold -s HTTPCACHE_DIR=demo_cache -O data/cold.jsonl
.\.venv\Scripts\python.exe -m scrapy crawl quotes -a run_id=warm -s HTTPCACHE_DIR=demo_cache -O data/warm.jsonl
```

Для сравнения начните с нового каталога кэша. Второй запуск использует сохранённые ответы.

## Качество данных

```powershell
.\.venv\Scripts\python.exe quality/analyze.py --label previous
```

После следующего сбора:

```powershell
.\.venv\Scripts\python.exe quality/analyze.py --label current
.\.venv\Scripts\python.exe quality/smoke_check.py quality/previous.json quality/current.json
```

`smoke_check.py` возвращает код 1, если число записей упало больше чем на 20 %
или доля строк с пустыми обязательными полями превысила 5 %.

## Файлы

- `labcrawler` — пауки, обработка записей и настройки Scrapy.
- `data/crawl.db` — база SQLite.
- `data/items.jsonl` — общая выгрузка.
- `data/stats_*.json` — статистика запусков.
- `jobstate` — очередь и состояние пауков.
- `quality` — CSV, полнота полей и агрегаты.
- [quality/quality_report.ipynb](quality/quality_report.ipynb) — анализ данных; запускается из `quality` с Python из `.venv`.
- [report.md](report.md) — отчёт.

## n8n

Нужен Node.js 22. В том же каталоге:

```powershell
npm install --prefix .lab-runtime n8n@1.121.3
$env:N8N_USER_FOLDER = "$PWD/.lab-runtime/user"
$env:N8N_RESTRICT_FILE_ACCESS_TO = "$PWD"
$env:N8N_LISTEN_ADDRESS = "127.0.0.1"
$env:N8N_PORT = "5679"
& .\.lab-runtime\node_modules\.bin\n8n.cmd start
```

Откройте http://localhost:5679, создайте локального пользователя и импортируйте
[nocode/workflow.json](nocode/workflow.json). Запустите узел `Manual start`.
Для ежедневного запуска включите workflow.

Результат сохраняется в `nocode/nocode_result.csv`, ошибки — в `nocode/error_log.csv`.
