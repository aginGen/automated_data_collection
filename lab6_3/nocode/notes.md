# n8n: обработка цитат

Вход — локальный снимок `input.json`, 39 записей. Normalize fields приводит текст, автора, теги и другие строки к NFKC, удаляет невидимые символы, нормализует пробелы, приводит теги к нижнему регистру и дату к ISO UTC. IF направляет записи с ошибками в `rejects.csv` (3), остальные (36) — в Remove Duplicates по `business_key`. После удаления двух повторов сохраняются 34 записи в `nocode_result.csv`. Ключ — SHA-256 от UTF-8 строки `source + "|" + source_record_id`, ведущие нули идентификатора сохраняются. Значения text и author не входят в ключ.

Schedule Trigger настроен на `0 8 * * *`, часовой пояс workflow `Asia/Yekaterinburg`. Workflow экспортирован с `active: false`: без активации запуск по расписанию не происходит. Снимки `screenshot_workflow.png` и `screenshot_result.png` получены в изолированном локальном n8n после успешного запуска этого workflow, второй снимок показывает 34 элемента и новый ключ. `metrics.json` содержит счётчики и времена двух CLI запусков. В CLI raw-объекте n8n 1.121.3 после завершения поле status осталось `running`, хотя `finished=true`, все исполненные узлы имеют `executionStatus=success`, а редактор сообщил `Workflow executed successfully`.

CSV перезаписывается целиком при каждом запуске. Два повторных прогона дали идентичные бинарные CSV, в итоговом файле нет повторов ключей. Это идемпотентная полная выгрузка одного снимка, а не построчный UPSERT: удалённые из нового входа записи исчезнут, изменения других существующих строк не сохраняются независимо от снимка. Для настоящего UPSERT подключите PostgreSQL, создайте UNIQUE по `business_key` и используйте `INSERT ... ON CONFLICT (business_key) DO UPDATE` для обновления полей. Для таблицы желательно транзакционно обрабатывать поток и отдельно сохранять rejects.

## Повторение

Из папки этой лабораторной запустите соседний переносимый комплект (Python 3.10+ и Node.js 22 в PATH):

```powershell
python ..\n8n_portable\launch.py --setup --browser
python ..\n8n_portable\launch.py --port 5679
```

Первая команда устанавливает зависимости; при последующих запусках достаточно второй. Launcher задаёт рабочий каталог n8n равным корню комплекта `n8n_portable`, создаёт `outputs/lab3`–`outputs/lab7` и запускает локальные вспомогательные сервисы ЛР4 и ЛР5. Откройте `http://127.0.0.1:5679`, импортируйте `nocode/workflow.json` этой лабораторной или соответствующий `../n8n_portable/workflows/labN.json` и выполните **Manual start**. Все относительные пути файлов в workflow отсчитываются от корня комплекта, а не от папки лабораторной. При запуске n8n из другой директории без launcher нужно самостоятельно установить рабочий каталог и создать папки. Расписание в экспорте выключено.

Входной снимок расположен в `../n8n_portable/labs/lab6_3/nocode/input.json`; результаты — `../n8n_portable/outputs/lab6/nocode_result.csv`, `outputs/lab6/rejects.csv` и журнал `outputs/lab6/error_log.csv`. Чтение и запись выполняются на машине n8n. Источники: [Schedule Trigger и часовой пояс](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.scheduletrigger/), [Remove Duplicates](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.removeduplicates/), [Read/Write Files from Disk](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.readwritefile/).
