# Проверка лабораторной 4

Обязательные элементы сверены с постановкой. Дополнительные задания на повышенный балл не выдаются за обязательные.

| Что проверено | Результат | Где смотреть |
|---|---|---|
| Вариант и объём | ScrapingCourse 147 + дополнительный Sandbox 200 = 347; 15 и 9 прокруток | report.md; metrics_browser.json |
| Диагностика | HTML-байты/число карточек/целевой текст в DOM/script-теги/без JS/XHR URL, метод, offset и HTML | artifacts/diagnostics.json; artifacts/diagnostic_details.json |
| Контрольная статическая страница | Корень /ecommerce разрешён robots; HTTP 200, 16 li.product в HTML; карточки по запрещённым путям не открывались | artifacts/control_static.json; artifacts/control_static.html |
| Браузер и ожидания | browser/context/page закрываются; UA, viewport, locale, таймауты; wait_for_function; пауза отдельно | collect.py: browser_source |
| Локаторы | Три семантических локатора, разбор смены класса/обёртки/языка и предложения замены | report.md: Playwright |
| Предохранители и сбои | 35 итераций, три без прироста, 200 строк на источник; TimeoutError, HTML/PNG/журнал, ненулевой выход | collect.py; artifacts/timeout_test |
| Массовое извлечение | Один evaluate_all, сохранён замер на 50 карточках; поэлементный образец читал два поля, массовый — все | metrics_browser.json; report.md |
| Альтернатива и блокировка | XHR у Course, облегчённый браузер у Sandbox; эффект медиа показан отдельно, без обещания снижения трафика | metrics_light.json; artifacts/browser_optimization.json; report.md |
| Сверка и качество | По 347 строк, совпали ключ/title/price/url, дублей и обязательных пропусков нет | comparison.json; quality_browser.json |
| Smoke-check | Порог 5%; сохранённый набор проходит, пустой и неполный наборы дают предупреждение | artifacts/smoke_check.json; collect.py: quality |
| n8n | Рендерер с JS и ожиданием, HTML Extract, Split/нормализация, 30 строк, CSV, расписание, ветка ошибки | render_api.py; nocode/workflow.json |
| Сравнение и рекомендации | Время/ответы/трафик/память/секунда на строку/устойчивость/воспроизводимость; три сценария и расчёт 334 рендеров | report.md: Сравнение |
| Условия доступа | Учебные сайты, паузы/robots, без обхода и реальной авторизации; товарный набор без ПД | report.md: Условия использования |

Отчёт: [PDF](report.pdf), [исходник](report.md). Показ: [defense.md](defense.md).
