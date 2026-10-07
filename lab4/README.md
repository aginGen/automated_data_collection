# Лабораторная 4. Сбор данных с динамических страниц

Вариант 3: [ScrapingCourse](https://www.scrapingcourse.com/infinite-scrolling).
На странице 147 уникальных товаров, поэтому для объёма от 200 записей добавлен
[ScrapingSandbox](https://scrapingsandbox.com/infinite-scroll). Итого — 347 товаров.

## Запуск

Команды выполняются из папки `lab4`. Нужен Python 3.10 или новее.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe collect.py --mode diagnose
.\.venv\Scripts\python.exe collect.py
```

Режимы `collect.py`:

- `diagnose` — исходный HTML и работа страницы без JavaScript.
- `browser` — сбор через Playwright.
- `light` — запросы к XHR ScrapingCourse и браузер без медиа для ScrapingSandbox.
- `all` — оба способа и сравнение; используется по умолчанию.

## Файлы

- `data_browser.csv` и `data_light.csv` — результаты двух способов.
- `collection_log*.csv` — журнал запросов.
- `comparison.json` — сравнение записей.
- `quality_*.json` и `metrics_*.json` — качество и замеры.
- `artifacts` — HTML, скриншоты и ошибки.
- [lab4.ipynb](lab4.ipynb) — запуск и анализ.
- [report.md](report.md) — отчёт.

Для блокнота выберите Python из `.venv` и выполняйте ячейки сверху вниз.

## Сервер для n8n

В отдельном терминале из папки `lab4`:

```powershell
.\.venv\Scripts\python.exe render_api.py --port 8789
```

Сервер открывает страницу, прокручивает её и возвращает HTML с товарами.
Workflow использует адрес `http://127.0.0.1:8789/render`.

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
