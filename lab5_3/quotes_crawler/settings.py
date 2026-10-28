BOT_NAME = "quotes_crawler"
SPIDER_MODULES = ["quotes_crawler.spiders"]
NEWSPIDER_MODULE = "quotes_crawler.spiders"
# Агент сообщает учебную цель; правила robots.txt соблюдаются для каждого домена.
USER_AGENT = "PGU-DataMining-Lab5/1.0 (educational; quotes.toscrape.com)"
ROBOTSTXT_OBEY = True
# Не более четырёх общих и двух одновременных запросов на домен.
CONCURRENT_REQUESTS = 4
CONCURRENT_REQUESTS_PER_DOMAIN = 2
# Базовый интервал 0,35 с; Scrapy рандомизирует его в пределах 0,5–1,5.
DOWNLOAD_DELAY = 0.35
RANDOMIZE_DOWNLOAD_DELAY = True
# AutoThrottle подстраивает задержку под ответ сайта; цель — один запрос одновременно.
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 0.35
AUTOTHROTTLE_MAX_DELAY = 5
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
# Сетевой запрос ограничен 20 секундами; повторяем дважды временные ошибки и 429.
DOWNLOAD_TIMEOUT = 20
RETRY_TIMES = 2
RETRY_HTTP_CODES = [500, 502, 503, 504, 522, 524, 408, 429]
# Глубина покрывает 10 страниц пагинации и карточку автора, предотвращая бесконечный обход.
DEPTH_LIMIT = 12
# Предохранитель для основного паука: максимум 300 элементов (источник содержит 100).
# Для tag-паука предел 10000 связей, поскольку один объект может иметь несколько тегов.
CLOSESPIDER_ITEMCOUNT = 300
# Ограничение общей длительности прогона — 15 минут.
CLOSESPIDER_TIMEOUT = 900
# По умолчанию сеть без кэша; для холодного/тёплого опыта включаем кэш через CLI.
# Нулевой срок хранения оставляет записи доступными между отладочными прогонами.
HTTPCACHE_ENABLED = False
HTTPCACHE_EXPIRATION_SECS = 0
# INFO фиксирует ход работы без больших отладочных логов.
LOG_LEVEL = "INFO"
ITEM_PIPELINES = {
    "quotes_crawler.pipelines.ValidationPipeline": 100,
    "quotes_crawler.pipelines.CleanPipeline": 200,
    "quotes_crawler.pipelines.DeduplicatePipeline": 300,
    "quotes_crawler.pipelines.SQLitePipeline": 400,
}
DATABASE_PATH = "data/crawl.db"
FEED_EXPORT_ENCODING = "utf-8"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
