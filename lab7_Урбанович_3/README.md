# Лабораторная 7. Устойчивый и легальный пайплайн

Урбанович И. О., ПМИ-2-2025, вариант 3: HTML + API. Номер в списке 26, `(26 mod 6)+1=3`. HTML-часть основана на BooksSpider из архивной лабораторной 5 с Books to Scrape, API-клиент взят из лабораторной 3.

[Отчёт PDF](report.pdf) содержит 13 разделов по ТЗ и занимает 5 страниц. [analysis.ipynb](analysis.ipynb) содержит выполненный анализ, таблицы, графики и исходные доказательства измерений. Для просмотра сохранённых результатов доступ к сети не нужен.

## Структура сдачи

```text
lab7_Урбанович_3/
├── src/
│   ├── limiter.py
│   ├── retry.py
│   ├── breaker.py
│   ├── detector.py
│   ├── observability.py
│   └── collect.py
├── state/
│   ├── etags.json
│   └── watermark.json
├── logs/
│   ├── run_<id>.jsonl
│   └── incidents/
├── reports/
│   ├── run_report_A.json
│   ├── run_report_B.json
│   ├── run_report_C.json
│   └── comparison.md
├── analysis.ipynb
├── nocode/
│   ├── workflow.json
│   ├── screenshot_*.png
│   └── nocode_notes.md
├── legal_checklist.md
├── report.pdf
├── requirements.txt
└── README.md
```

## Сохранённые результаты

Основная локальная серия A/B/C содержит одинаковые 165 записей: 60 HTML + 105 API. Каждый режим сделал шесть запросов. Тело ответов A и B составило 23 411 байт, C — 343 байта. Цена вежливости B−A равна 7,453 с, экономия трафика C относительно B — 98,53%. Это повторный сбор с заранее заполненным кэшем, его подготовка вынесена за границы сравнения.

Три обязательных JSON в `reports/` содержат метрики и поле `records` с полным результатом каждого режима. [comparison.md](reports/comparison.md) сопоставляет режимы и отдельно описывает внешние измерения и локальные проверки.

Исторические внешние прогоны от 27 октября, robots.txt, результаты отдельных стендов и 60 строк n8n сохранены в `metadata.lab7_evidence` самого блокнота. Внешний срез содержит 63 книги и проверяет условные запросы и gzip. Поддержка курсора изменений Open Library не предполагается. Доказательства внешнего и локального сбора разделены.

Все графики встроены в блокнот и PDF. Журналы HTTP-попыток сохранены в `logs/run_<id>.jsonl`, артефакты блокировок — в `logs/incidents/`.

## Установка

Нужен Python 3.10+. Откройте PowerShell в папке лабораторной. Окружение создаётся за её пределами:

```powershell
New-Item -ItemType Directory -Force ..\.lab-work | Out-Null
python -m venv ..\.lab-work\lab7-venv
..\.lab-work\lab7-venv\Scripts\python.exe -m pip install -r requirements.txt
```

Откройте `analysis.ipynb` в VS Code или Jupyter и выберите это окружение. Ячейки читают сохранённые данные, сверяют отчёты с JSONL и строят графики внутри блокнота. HTTP-запросов при выполнении аналитических ячеек нет.

## Проверки и воспроизведение

```powershell
..\.lab-work\lab7-venv\Scripts\python.exe -B -X utf8 src/collect.py compare
..\.lab-work\lab7-venv\Scripts\python.exe -B -X utf8 src/collect.py self-test
..\.lab-work\lab7-venv\Scripts\python.exe -B -X utf8 src/collect.py fixture
..\.lab-work\lab7-venv\Scripts\python.exe -B -X utf8 src/collect.py benchmark
```

`compare` показывает сохранённые показатели. `self-test` выполняет 10 проверок. `fixture` воспроизводит два 500, открытие предохранителя, работу второго источника, восстановление после паузы и однократный 404. `benchmark` повторяет локальный A/B/C с условными запросами, gzip и курсором изменений.

Стенды находятся внутри `collect.py` и работают в отдельной временной копии через localhost. Они печатают фактические результаты и не перезаписывают измерения, с которыми подготовлен отчёт. Ключ `-B` предотвращает создание `__pycache__` в папке сдачи.

Для нового внешнего сбора доступны B и C:

```powershell
..\.lab-work\lab7-venv\Scripts\python.exe -B -X utf8 src/collect.py B
..\.lab-work\lab7-venv\Scripts\python.exe -B -X utf8 src/collect.py C
```

Эти команды отправляют реальные запросы. Путь нового отчёта во временном каталоге выводится в консоль. Сохранённые отчётные A/B/C не заменяются. Наивный внешний режим A запрещён, он доступен только через локальный `benchmark`.

Между прогонами `state/etags.json` хранит валидаторы и историю, `state/watermark.json` — курсоры по разделам feed. Файлы межпроцессных блокировок создаются в системном временном каталоге. При запуске четырёх процессов один владеет доменом, остальные отказываются от его обработки.

## n8n

[workflow.json](nocode/workflow.json) содержит сбор 60 книг и ветку Error Trigger → Telegram в одном workflow. Wait, batch=1, Retry On Fail, проверка IF и ежедневное расписание 08:00 Asia/Yekaterinburg сохранены. Расписание выключено.

Для n8n 1.121.3 используется совместимая версия Node.js, например 22. Из папки лабораторной:

```powershell
New-Item -ItemType Directory -Force ..\.lab-work | Out-Null
npm.cmd install --prefix ..\.lab-runtime n8n@1.121.3
$env:N8N_USER_FOLDER = Join-Path $env:TEMP 'urbanovich-lab7-n8n'
$env:N8N_LISTEN_ADDRESS = '127.0.0.1'
$env:N8N_PORT = '5687'
node ..\.lab-runtime\node_modules\n8n\bin\n8n start
```

Откройте `http://127.0.0.1:5687` и импортируйте единственный `nocode/workflow.json`. Процесс должен работать из папки лабораторной. Результат CSV и журнал ошибки записываются в `../.lab-work/`, за пределами сдаваемой папки. Настройка собственного бота, особенности Error Trigger, результаты испытаний и стоимость приведены в [nocode_notes.md](nocode/nocode_notes.md).

Переносимый экспорт не содержит токена, Chat ID и учётных данных. Ручная отправка одного тестового сообщения в настроенном локальном экземпляре проверена. Автоматическая обработка ошибки проверена отдельно на локальном HTTP-получателе.

## Суть работы

Нужно доработать прежний сборщик: управлять скоростью и повторами, изолировать отказы источника, экономить трафик и обнаруживать заглушки. Для варианта 3 обязательны работа второго источника при 500 у первого и отсутствие повторов 404. Результат подтверждается журналами, тремя режимами A/B/C, no-code сценарием и [правовым чек-листом](legal_checklist.md).
