# Лабораторная 7. Устойчивый сбор

Вариант 3: смешанный HTML/API-источник, сбой 500 у одного источника и 404 на части URL.
Проверяются ограничение скорости, повторы, предохранитель, кэш и диагностика блокировок.

A/B/C выполняются на собственном локальном HTTP-стенде.
В нём 30 ранее сохранённых цитат и 30 книг. Это учебные ответы, а не новые ответы внешних сайтов.

## Запуск

Python 3.10 или новее. Из папки lab7:

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe training_server.py
~~~

Оставьте этот терминал открытым. Во втором терминале из той же папки:

~~~powershell
.\.venv\Scripts\python.exe -m src.collect --profile A
.\.venv\Scripts\python.exe -m src.collect --profile B
.\.venv\Scripts\python.exe -m src.collect --profile C
~~~

B наполняет кэш; C использует его и версии manifest. Все три результата содержат 60 записей.
У повторного C новых записей по сети нет: четыре ответа 304 и шесть пропущенных страниц.
Режим A разрешён кодом только на локальном стенде, максимум 30 запросов.

Сценарии отказов:

~~~powershell
.\.venv\Scripts\python.exe -m src.collect --scenario faults
.\.venv\Scripts\python.exe -m src.collect --scenario blocked
$LASTEXITCODE
~~~

Красный статус и код 2 в этих сценариях ожидаемы.
Сервер запоминает число подготовленных ошибок. Для точного повтора сценариев остановите его Ctrl+C и запустите снова.

Реальная проверка (не нужна для локального показа):

~~~powershell
.\.venv\Scripts\python.exe -m src.collect --scenario real
~~~

Она соблюдает robots.txt: при запрете URL пропускается. Блокировки не обходятся.

## Файлы

- `src/`: ограничитель, повторы, предохранитель, детектор, логи и сбор.
- `fixtures/`: исходные учебные ответы.
- `state/`: HTTP-валидаторы, кэш и watermark.
- `logs/`: структурные JSONL и артефакты инцидентов.
- `reports/`: A/B/C, экономия нагрузки и сценарии отказов.
- [analysis.ipynb](analysis.ipynb): таблицы и два графика по журналам.
- [legal_checklist.md](legal_checklist.md): правила доступа и хранения.
- [report.pdf](report.pdf): отчёт; [report.md](report.md): исходник.
- [defense.md](defense.md): порядок показа.

## n8n

Node.js 22; сервер training_server.py должен работать. Из папки lab7:

~~~powershell
npm install --prefix .lab-runtime n8n@1.121.3
$env:N8N_USER_FOLDER = "$PWD/.lab-runtime/user"
$env:N8N_RESTRICT_FILE_ACCESS_TO = "$PWD"
$env:N8N_LISTEN_ADDRESS = "127.0.0.1"
$env:N8N_PORT = "5679"
& .\.lab-runtime\node_modules\.bin\n8n.cmd start
~~~

При уже работающем n8n пропустите запуск второго сервера.
Откройте http://localhost:5679, импортируйте [workflow.json](nocode/workflow.json).
В Save CSV и Save error log укажите абсолютные пути внутри своей папки lab7.
Корень N8N_RESTRICT_FILE_ACCESS_TO должен разрешать эти файлы.

Manual start получает три страницы API по десять строк.
Wait даёт паузу, HTTP-коды разбираются отдельно: 429/5xx повторяются ограниченно, 404 уходит в Stop and Error.
Обычный результат: 30 строк, три HTTP-запроса.
Daily schedule настроен; активируйте workflow только если нужен ежедневный запуск.
Секретов источников нет. Стоимость локальной платформы и API равна нулю; оборудование и сопровождение не оценивались.

Сверка обязательных элементов и файлов: [verification.md](verification.md).
