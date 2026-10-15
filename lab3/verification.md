# Проверка лабораторной 3

Обязательные элементы сверены с постановкой. Дополнительные задания на повышенный балл не выдаются за обязательные.

| Что проверено | Результат | Где смотреть |
|---|---|---|
| Вариант и объём | 360 книг, четыре страницы по 90; Search + Authors | report.md: 1–4; collection_log.csv |
| HTTP и ошибки | Session, User-Agent/Accept, timeout, статус/Content-Type, первые 200 байт; только 429/5xx с backoff/Retry-After | collect.py: get_json |
| Пагинация и ограничители | page_size/max_records/max_pages; смещение по длине ответа, total/пустая порция; пауза 1,1 с | collect.py: paginate |
| Нормализация и обогащение | json_normalize sep, массив языков record_path/meta; merge many_to_one, 360 → 360, 357 совпадений | collect.py: normalize_books; book_languages.csv |
| Качество | Полнота всех полей, nullable числа/UTC, 0 дублей и обязательных пропусков, четыре бизнес-проверки | quality.json; completeness.csv; report.md: 5 |
| Необычные значения | 1,5 IQR: 11 лет и 50 чисел изданий; флаги не равны ошибке, удалений нет | outliers.json; lab3.ipynb |
| Повтор | state.json, известные ключи и watermark; сохранённый повтор без новых строк | metrics_second.json; report.md: 7 |
| n8n | 30 книг, три порции, 3+ преобразования, расписание, CSV и журнал ошибки | nocode/workflow.json; nocode/result.png |
| Сравнение | Подготовка/объём/время/пагинация/ошибки/воспроизводимость/100 запусков/порог входа; объяснён разный объём | report.md: 7 |
| Правовая оценка и источники | Условия API, потенциальные ПД, 152-ФЗ и срок удаления; ссылки | report.md: 8–9 |
| Воспроизведение | README, зависимости, блокнот, raw/clean/log/state и экспорт workflow | README.md; lab3.ipynb |

Отчёт: [PDF](report.pdf), [исходник](report.md). Показ: [defense.md](defense.md).
