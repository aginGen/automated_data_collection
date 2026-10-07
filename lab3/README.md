# Лабораторная 3. Сбор данных через REST API

Вариант 3: Open Library Search API и Authors API.
Собраны книги по запросу `python programming` и сведения об авторах.

## Запуск

Команды выполняются из папки `lab3`. Нужен Python 3.10 или новее.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe collect.py
```

Для повторного сбора:

```powershell
.\.venv\Scripts\python.exe collect.py --run-label second
```

Повторный запуск использует кэш авторов и добавляет только новые книги.
Между запросами выдерживается 1,1 секунды. API-ключ не нужен.

Для новой выборки используйте отдельную папку:

```powershell
.\.venv\Scripts\python.exe collect.py --query "data science" --output output/data_science
```

Параметры `--page-size`, `--max-records` и `--max-pages` ограничивают объём сбора.
Сырые данные и `state.json` нужно сохранять вместе.

## Файлы

- `collect.py` — запросы, обработка и сохранение данных.
- `data_raw.jsonl` — исходные записи книг.
- `data_clean.csv` — итоговая таблица.
- `book_languages.csv` — языки книг.
- `authors_cache.json` — кэш ответов Authors API.
- `collection_log*.csv` — журнал запросов.
- `state.json` — состояние повторного сбора.
- `quality.json` и `completeness.csv` — качество данных.
- `metrics_*.json` — время, запросы и память.
- [lab3.ipynb](lab3.ipynb) — сбор, анализ и сравнение с n8n.
- [report.md](report.md) — отчёт.

Для блокнота выберите Python из `.venv` и выполняйте ячейки сверху вниз.

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
