# Лабораторная 6. Хранение и качество данных

Вариант 3: цитаты и авторы. HTML из Quotes to Scrape и учебный API DummyJSON.
Из 452 входных строк получены 414 уникальных цитат, 98 авторов и 205 связей с тегами.
32 входные строки намеренно испорчены и помечены `_synthetic`.

## Запуск

Python 3.10 или новее. Команды из папки `lab6`:

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m src.rebuild
.\.venv\Scripts\python.exe -m db.load --demonstrate
~~~

Пересборка работает из сохранённого raw без запросов к сайтам.
Manifest проверяет, что прежние строки raw не изменились.
Повторный обычный запуск не обновляет неизменившиеся строки warehouse.db.
Демонстрация трёх загрузок пересоздаёт только `db/idempotency_demo.db`.

Остановка при плохом качестве:

~~~powershell
.\.venv\Scripts\python.exe -m src.rebuild --force-red
$LASTEXITCODE
~~~

Ожидается код 2. Это подготовленная демонстрация; mart не перезаписывается.

## Файлы

- `raw/`: исходные JSONL, метаданные происхождения и manifest.
- `clean/`: Parquet, протокол, ошибки, контракт, метрики и сравнение форматов.
- `db/schema.sql`: связи и ограничения; `db/warehouse.db`: чистый набор.
- `mart/views/`: три аналитических представления.
- `mart/snapshots/`: снапшоты с разбиением по дате сбора.
- [quality_report.ipynb](quality_report.ipynb): таблицы, проверки и графики.
- [report.pdf](report.pdf): отчёт; [report.md](report.md): его исходник.
- [defense.md](defense.md): порядок показа и команды.

Блокнот читает сохранённые результаты. Выберите Python из .venv и выполните ячейки сверху вниз.

## n8n

Node.js 22. Из папки lab6:

~~~powershell
npm install --prefix .lab-runtime n8n@1.121.3
$env:N8N_USER_FOLDER = "$PWD/.lab-runtime/user"
$env:N8N_RESTRICT_FILE_ACCESS_TO = "$PWD"
$env:N8N_LISTEN_ADDRESS = "127.0.0.1"
$env:N8N_PORT = "5679"
& .\.lab-runtime\node_modules\.bin\n8n.cmd start
~~~

Откройте http://localhost:5679 и импортируйте [workflow.json](nocode/workflow.json).
Если n8n уже работает, второй сервер запускать не нужно.
В узлах Read source snapshot, Save CSV и Save rejects задайте абсолютные пути к файлам внутри своей папки lab6.
Для Windows используйте прямые слеши: `D:/.../lab6/nocode/input.json`.
Корень доступа N8N_RESTRICT_FILE_ACCESS_TO должен включать эти файлы.

Manual start запускает обработку 39 строк: 34 проходят, три попадают в rejects, два дубля удаляются.
Выходные файлы создаёт сам n8n. Python после экспорта не нужен.
Daily schedule настроен; автоматическое расписание работает после активации workflow.
Секретов источников нет. Учётная запись n8n хранится только в локальном профиле редактора.

DummyJSON добавлен как учебный API для нужного объёма. Его поля и отсутствие тегов явно разобраны в отчёте.

Сверка обязательных элементов и файлов: [verification.md](verification.md).
