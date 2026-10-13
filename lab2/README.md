# Лабораторная 2. Сбор данных с HTML-страниц

Сбор книг с [Books to Scrape](https://books.toscrape.com/) через BeautifulSoup и Octoparse.
Получено по 40 книг с двух страниц каталога.

## Запуск

Команды выполняются из папки `lab2`. Нужен Python 3.10 или новее.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scraper.py --limit 40
```

После экспорта CSV из Octoparse:

```powershell
.\.venv\Scripts\python.exe normalize_octoparse.py
.\.venv\Scripts\python.exe compare_results.py
```

`--limit` задаёт число уникальных книг, минимум — 20.
`--timeout` задаёт тайм-аут запроса, `--retries` — число повторов при временной ошибке.

## Файлы

- `scraper.py` — сбор и очистка данных.
- `normalize_octoparse.py` — очистка экспорта Octoparse.
- `compare_results.py` — сравнение результатов по UPC.
- `books.csv` — 40 книг, 6 полей.
- `octoparse_raw.csv` — исходный экспорт Octoparse.
- `octoparse_books.csv` — очищенный экспорт, 5 полей.
- [lab2.ipynb](lab2.ipynb) - селекторы, очистка, таблицы и сравнение.
- [PDF-отчёт](report.pdf) - результаты, настройка Octoparse и скриншоты.

Для показа выберите Python из .venv и выполните ячейки блокнота сверху вниз.
Блокнот читает сохранённые CSV; новый сбор запускается отдельно через scraper.py.

Пять общих полей совпадают у всех 40 книг. Категория сохранена только в `books.csv`:
в исходном экспорте Octoparse она заполнена лишь для пяти книг из Poetry.

Редактируемый исходник отчёта: [report.md](report.md).
