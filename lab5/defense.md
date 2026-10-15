# Защита лабораторной 5

## Что сделано

**Мой вариант 3: цитаты и страницы авторов Quotes to Scrape.**
Нужно показать краулер: страницы каталога → карточки → страницы авторов.
На Quotes всего 100 цитат. Для минимума 300 добавлен дополнительный Books to Scrape: 304 книги.
В БД 404 записи двух видов; это не 404 цитаты.

## 1. Подготовка и обзор

Новый терминал из корня dataMining:

~~~powershell
cd lab5
$labPython = (Resolve-Path ..\.lab-runtime\venv\Scripts\python.exe).Path
~~~

Откройте report.pdf, labcrawler/spiders/quotes.py, pipelines.py и settings.py.
В quality/quality_report.ipynb выберите подготовленный Python и выполните ячейки сверху вниз: он читает сохранённые данные.

Фраза: «Scrapy управляет очередью URL и вызывает callbacks. Паук извлекает поля, pipelines проверяют и сохраняют записи».

## 2. Показать паука

В quotes.py найдите parse, ссылку next и запрос страницы автора.
Покажите передачу цитаты через cb_kwargs и обработку ответа автора.
Укажите allowed_domains и ограничения глубины/времени.

Схема: каталог → цитата и ссылка автора → страница автора → дополненная запись.
Авторы кэшируются; одна и та же страница не должна скачиваться для каждой цитаты.

## 3. Показать обработку и настройки

В pipelines.py идут валидация → очистка → дедупликация → SQLite.
Цитата определяется текстом и автором, книга - UPC.
SQLite получает записи пакетами; обязательные пропуски уходят в DropItem.

В settings.py покажите:
ROBOTSTXT_OBEY, USER_AGENT, DOWNLOAD_DELAY, AUTOTHROTTLE, RETRY_TIMES, DOWNLOAD_TIMEOUT, DEPTH_LIMIT, HTTPCACHE и ITEM_PIPELINES.
Рядом оставлены короткие комментарии, требуемые заданием.

## 4. Остановка и продолжение

Для каждого показа нужен НОВЫЙ каталог JOBDIR. Команды сами создают уникальное имя:

~~~powershell
$demoId = [guid]::NewGuid().ToString("N").Substring(0,8)
$jobDir = "jobstate/demo_$demoId"
& $labPython -m scrapy crawl quotes -a "run_id=pause_$demoId" -s "JOBDIR=$jobDir" -s CLOSESPIDER_ITEMCOUNT=35 -O "data/pause_$demoId.jsonl"
& $labPython -m scrapy crawl quotes -a "run_id=resume_$demoId" -s "JOBDIR=$jobDir" -s CLOSESPIDER_ITEMCOUNT=300 -O "data/resume_$demoId.jsonl"
~~~

В первом логе покажите item_scraped_count и причину закрытия.
Во втором - продолжение, dupefilter и итоговый объём.
В проверенном запуске было 35 + 65 = 100 цитат.
Граница остановки может немного превыситься из-за запросов в работе.

JOBDIR хранит очередь и посещённые URL. Для продолжения используется тот же путь.
Не запускайте два паука одновременно с одним JOBDIR.

## 5. Кэш и качество

Покажите сохранённые data/stats_cache_1.json и data/stats_cache_2.json:
в тёплом запуске 211 cache hit и существенно меньше время.
JOBDIR и HTTP-кэш решают разные задачи: очередь и копии ответов.

Для нового сравнения кэша (дольше, необязательно на короткой защите):

~~~powershell
$cacheDir = "demo_cache_" + [guid]::NewGuid().ToString("N").Substring(0,8)
& $labPython -m scrapy crawl quotes -a run_id=cold_demo -s "HTTPCACHE_DIR=$cacheDir" -O data/cold_demo.jsonl
& $labPython -m scrapy crawl quotes -a run_id=warm_demo -s "HTTPCACHE_DIR=$cacheDir" -O data/warm_demo.jsonl
~~~

Качество:

~~~powershell
& $labPython quality/analyze.py
~~~

Покажите quality/current.json и таблицы блокнота: 100 цитат, 304 книги, ноль дублей и пустых обязательных полей.
В БД откройте таблицы books и quotes; если расширения SQLite нет, достаточно таблиц блокнота.
Контроль деградации находится в quality/smoke_check.py: падение числа строк >20% или обязательные пропуски >5% дают код 1.

## 6. n8n

Откройте http://localhost:5679 и workflow «Lab 5 Two level quote collection».
При необходимости импортируйте lab5/nocode/workflow.json и проверьте абсолютные пути сохранения.

1. Узел загрузки страниц: три страницы по десять цитат.
2. Узел перехода к автору: второй уровень обхода.
3. Дедупликация по ключу цитаты.
4. Расписание, таймаут и ветка ошибки.
5. Execute workflow.
6. Выходная таблица и nocode/nocode_result.csv: 30 цитат.

Фраза: «Здесь тоже два уровня. В Scrapy есть постоянная очередь и JOBDIR; в этом небольшом n8n-сценарии их нет».

## 7. Завершение

Покажите отчёт: структура пауков, настройки, остановка/продолжение, качество, сравнение и скриншоты.
Книги добавлены только для объёма; основной предмет варианта - цитаты и авторы.

Ветка ошибки n8n теперь заканчивается Stop and notify после сохранения CSV. Подготовленный 404 проверен; подтверждение — nocode/metrics_error_demo.json.
