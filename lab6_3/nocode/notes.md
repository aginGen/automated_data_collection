# n8n: обработка цитат

Вход — локальный снимок `input.json`, 39 записей. Normalize fields приводит текст, автора, теги и другие строки к NFKC, удаляет невидимые символы, нормализует пробелы, приводит теги к нижнему регистру и дату к ISO UTC. IF направляет записи с ошибками в `rejects.csv` (3), остальные (36) — в Remove Duplicates по `business_key`. После удаления двух повторов сохраняются 34 записи в `nocode_result.csv`. Ключ — SHA-256 от UTF-8 строки `source + "|" + source_record_id`, ведущие нули идентификатора сохраняются. Значения text и author не входят в ключ.

Schedule Trigger настроен на `0 8 * * *`, часовой пояс workflow `Asia/Yekaterinburg`. Workflow экспортирован с `active: false`: без активации запуск по расписанию не происходит. Снимки `screenshot_workflow.png` и `screenshot_result.png` получены в изолированном локальном n8n после успешного запуска этого workflow, второй снимок показывает 34 элемента и новый ключ. `metrics.json` содержит счётчики и времена двух CLI запусков. В CLI raw-объекте n8n 1.121.3 после завершения поле status осталось `running`, хотя `finished=true`, все исполненные узлы имеют `executionStatus=success`, а редактор сообщил `Workflow executed successfully`.

CSV перезаписывается целиком при каждом запуске. Два повторных прогона дали идентичные бинарные CSV, в итоговом файле нет повторов ключей. Это идемпотентная полная выгрузка одного снимка, а не построчный UPSERT: удалённые из нового входа записи исчезнут, изменения других существующих строк не сохраняются независимо от снимка. Для настоящего UPSERT подключите PostgreSQL, создайте UNIQUE по `business_key` и используйте `INSERT ... ON CONFLICT (business_key) DO UPDATE` для обновления полей. Для таблицы желательно транзакционно обрабатывать поток и отдельно сохранять rejects.

## Повторение

В PowerShell из корня `lab6_3` (нужен установленный n8n 1.121.3):

```powershell
$env:N8N_USER_FOLDER='D:\ПГУ ПРАКТИКА\Мага2Курс\DataMining\.lab6-work\n8n'
$env:GENERIC_TIMEZONE='Asia/Yekaterinburg'
$env:N8N_DIAGNOSTICS_ENABLED='false'
$n8n='D:\ПГУ ПРАКТИКА\Мага2Курс\DataMining\automated_data_collection\.lab-runtime\node_modules\n8n\bin\n8n'
node $n8n import:workflow --input=nocode/workflow.json
node $n8n execute --id=Lab6QuotesVariant3 --rawOutput
```

Относительные пути в workflow требуют запуска из корня лабораторной, чтение/запись файлов выполняется на машине n8n. `--file` в данном runtime не сработал, поэтому используется импорт и `--id`. Источники: [Schedule Trigger и часовой пояс](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.scheduletrigger/), [Remove Duplicates](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.removeduplicates/), [Read/Write Files from Disk](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.readwritefile/).
