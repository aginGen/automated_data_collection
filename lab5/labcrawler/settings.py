BOT_NAME = "labcrawler"
SPIDER_MODULES = ["labcrawler.spiders"]
NEWSPIDER_MODULE = "labcrawler.spiders"

# Обозначает учебный краулер в HTTP-запросах.
USER_AGENT = "university-data-collection-lab5/1.0"
# Соблюдает ограничения robots.txt.
ROBOTSTXT_OBEY = True

# Два параллельных запроса ограничивают нагрузку; на домен действует тот же предел.
CONCURRENT_REQUESTS = 2
CONCURRENT_REQUESTS_PER_DOMAIN = 2
# Пауза 0,25 секунды случайно изменяется между запросами.
DOWNLOAD_DELAY = 0.25
RANDOMIZE_DOWNLOAD_DELAY = True

# Задержка подстраивается под время ответа; цель - один запрос в работе на слот.
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 0.3
AUTOTHROTTLE_MAX_DELAY = 3
AUTOTHROTTLE_TARGET_CONCURRENCY = 1

# Ограничивает время запроса; временные HTTP-ошибки повторяются не более двух раз.
DOWNLOAD_TIMEOUT = 25
RETRY_TIMES = 2
RETRY_HTTP_CODES = [429, 500, 502, 503, 504]
# Ограничения глубины, числа записей, страниц и времени останавливают затянувшийся обход.
DEPTH_LIMIT = 25
CLOSESPIDER_ITEMCOUNT = 300
CLOSESPIDER_PAGECOUNT = 500
CLOSESPIDER_TIMEOUT = 900

# Ответы хранятся сутки для повторных запусков; ответы с временными ошибками не кэшируются.
HTTPCACHE_ENABLED = True
HTTPCACHE_EXPIRATION_SECS = 86400
HTTPCACHE_DIR = "httpcache"
HTTPCACHE_IGNORE_HTTP_CODES = [429, 500, 502, 503, 504]
# INFO сохраняет ход обхода и ошибки без подробной отладочной трассировки.
LOG_LEVEL = "INFO"
# UTF-8 сохраняет названия и цитаты без потери символов.
FEED_EXPORT_ENCODING = "utf-8"
# Записи последовательно проходят проверку, очистку, дедупликацию и запись в SQLite.
ITEM_PIPELINES = {
    "labcrawler.pipelines.ValidationPipeline": 100,
    "labcrawler.pipelines.CleaningPipeline": 200,
    "labcrawler.pipelines.DeduplicationPipeline": 300,
    "labcrawler.pipelines.SQLitePipeline": 400,
}
# Считает реальные сетевые ответы и объём данных отдельно от попаданий в кэш.
DOWNLOADER_MIDDLEWARES = {"labcrawler.middlewares.NetworkMetricsMiddleware": 850}
