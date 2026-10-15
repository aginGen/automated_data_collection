# Проверка лабораторной 5

Обязательные элементы сверены с постановкой. Дополнительные задания на повышенный балл не выдаются за обязательные.

| Что проверено | Результат | Где смотреть |
|---|---|---|
| Вариант и объём | 100 цитат с десяти страниц + 304 книги с 20 страниц; два уровня, ITEMCOUNT=300 | report.md; data/stats_*.json |
| Проект и архитектура | Штатный Scrapy-проект, Items, Spider vs CrawlSpider, Scheduler/Downloader/Pipeline, отдельная логика | scrapy.cfg; labcrawler; report.md |
| Паук | response.follow, cb_kwargs, отсутствующие поля, errback, closed со статистикой | labcrawler/spiders |
| Pipeline | Валидация → очистка → дедупликация → БД; DropItem и отдельные счётчики, executemany пакетами по 50 | labcrawler/pipelines.py |
| Настройки | Обязательные ограничения, robots/AutoThrottle/cache/таймаут/повторы и короткие комментарии | labcrawler/settings.py |
| JOBDIR | 35 + 65; прежняя очередь; dupefilter=1 во втором прогоне | jobstate; data/stats_resume_*.json |
| HTTP-кэш | cache_1: store114/hit97/36,781с; cache_2: store0/hit211/2,750с | data/stats_cache_*.json |
| Качество и статистика | Уникальные ключи, полнота всех полей, брак по причине, коды/повторы/байты/длительность и 2+ агрегата | quality/current.json; completeness.csv; report.md |
| Smoke-check | Падение >20% или пропуски >5% дают код1; три наблюдаемых демонстрационных случая | quality/smoke_check.py; smoke_demonstration.json |
| n8n | 30 цитат, пагинация, второй уровень, Loop/Wait, дедупликация/типы/CSV, расписание и Retry On Fail | nocode/workflow.json |
| Ошибка n8n | CSV журнала → Stop and notify; подготовленный 404 завершил сценарий ошибкой; обычный прогон дал30 | nocode/metrics_error_demo.json; metrics_verification.json |
| Сравнение | Все показатели и рекомендации для 500/40000/100 страниц; стоимость поддержки субъективна | report.md: Сравнение |
| Право и редизайн | Риски селекторов/полнота/счётчики, robots/нагрузка/ПД/152-ФЗ/срок и ссылки | report.md: Устойчивость и условия использования |

Отчёт: [PDF](report.pdf), [исходник](report.md). Показ: [defense.md](defense.md).
