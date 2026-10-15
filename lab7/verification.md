# Проверка лабораторной 7

Обязательные элементы сверены с постановкой. Дополнительные задания на повышенный балл не выдаются за обязательные.

| Что проверено | Результат | Где смотреть |
|---|---|---|
| Вариант | HTML+API; 500 одного источника/работа второго и 404 частиURL; основа собственных сборщиков3/5 | report.md: 1–2; fixtures/README.md |
| Скорость | Bucket2rps, burst1, jitter25%, адаптация; измеренный минимум0,533/0,534с | src/limiter.py; reports/rate_limits.json |
| Распределение | Один владелец домена и межпроцессная файловая блокировка; четыре процесса не умножают лимит | src/limiter.py: DomainLease; report.md: 3 |
| robots | can_fetch/crawl_delay/request_rate/Sitemap; 404 разобран; /search не запрашивается | reports/real_probe.json; robots_review.json; robots_openlibrary.txt |
| Повторы | Классификация, full jitter/cap/попытки/бюджет, оба Retry-After; 4xx кроме429 не повторяются | src/retry.py; report.md: 4 |
| Предохранитель | Closed/open/half-open/closed, изоляция, пробный успех и счётчик | reports/scenario_faults.json; журнал указан внутри |
| Экономия | Отдельные до/после запросов и тел: conditional GET, gzip, watermark; заголовки не включены | reports/load_savings.json; report.md: 7 |
| Детектор | Коды/маркеры/размер/ожидаемые записи; заглушка200, артефакты, остановка домена, код2; реальный HTML проверен | src/detector.py; reports/scenario_blocked.json; logs/incidents |
| История и пороги | Медианы объёма/тела, 6 порогов с причинами; списки реально сработавших оповещений | src/observability.py; reports/scenario_*.json |
| Логи и метрики | JSONL с обязательными полями; все показатели, коды и p95 в JSON и блокноте;2 графика | logs; reports; analysis.ipynb |
| A/B/C | 60 одинаковых архивных записей, A тольколокально ≤30запросов, цена вежливости/экономия и объяснение304 | reports/run_report_A.json и B/C; report.md: 8 |
| n8n | 30строк, Wait/Loop, ограниченные повторы, IF, журнал и UI-ошибка, расписание; 429/404 проверены | nocode/workflow.json; metrics*.json |
| Ограничения и стоимость | Отдельная колонка; breaker/304/общий лимит не реализованы;30 исполнений и90запросов, локальная плата0 | report.md: 10–11; nocode/nocode_notes.md |
| Правовой чек-лист | Все пункты: источники/условия/robots/авторизация/обход/частота/ПД/основание/хранение/контакт/реакция | legal_checklist.md; report.md: 12 |

Отчёт: [PDF](report.pdf), [исходник](report.md). Показ: [defense.md](defense.md).
