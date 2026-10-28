# n8n: двухуровневый сбор цитат

`workflow.json` предназначен для n8n 1.121.3. Ручной запуск и расписание ежедневно в 08:00 по Asia/Yekaterinburg (для расписания требуется активация). Три страницы каталога проходят HTML → Split Out → извлечение полей. Loop Over Items последовательно запрашивает страницы авторов, извлекает биографические данные, сохраняет контекст и ждёт 0,5 с. Затем Remove Duplicates удаляет повторы по нормализованным автору и цитате, Code приводит дату к ISO и теги к нижнему регистру, и CSV сохраняется на диск. Пустой массив тегов допустим. Для даты проверяются фактические дни месяца и високосный год; отсутствие обязательных полей приводит к ветке ошибки. `business_key` — SHA-256 от нормализованных `author.lower() + "\n" + quote`.

## Запуск

Нужны Python 3, Node.js 22.11 и n8n 1.121.3. Из корня лабораторной работы запустите локальный приёмник в отдельном терминале:

```powershell
python .\nocode\notification_server.py
```

Откройте http://127.0.0.1:5686/ и оставьте вкладку открытой: она опрашивает приёмник каждые 2 секунды и показывает полученное уведомление красным блоком. Это локальная веб-страница, а не системное push-уведомление; внешние сообщения не отправляются. Приёмник слушает только 127.0.0.1:5686, принимает ограниченный JSON и записывает `nocode/notifications.jsonl`.

Во втором PowerShell, также из корня лабораторной работы (для n8n в PATH):

```powershell
$env:N8N_USER_FOLDER = Join-Path $env:TEMP 'lab5-n8n-isolated'
$env:N8N_PORT = '5685'
$env:N8N_LISTEN_ADDRESS = '127.0.0.1'
$env:N8N_RESTRICT_FILE_ACCESS_TO = (Get-Location).Path
$env:N8N_DIAGNOSTICS_ENABLED = 'false'
$env:NODE_FUNCTION_ALLOW_BUILTIN = 'crypto'
$env:GENERIC_TIMEZONE = 'Asia/Yekaterinburg'
$env:NODE_TLS_REJECT_UNAUTHORIZED = '1'
$env:NO_PROXY = 'localhost,127.0.0.1,quotes.toscrape.com'
n8n import:workflow --input=./nocode/workflow.json
n8n start
```

Открыть http://localhost:5685, выполнить локальную настройку владельца и запустить workflow через Manual start. Активируйте его для расписания. Путь `nocode/nocode_result.csv` разрешается от рабочей директории n8n, поэтому запускайте его из корня лабораторной работы. Если приёмник выключен, ошибка завершает workflow с отдельным сообщением `local notification FAILED`; нельзя считать такое уведомление доставленным. При неуспешном выполнении предыдущий CSV сохраняется: проверяйте статус запуска и время записи файла.

## Подтверждение

`nocode_result.csv` создан фактическим успешным ручным выполнением n8n #8: 30 уникальных записей, 10 на каждой странице, 33,100 с. `screenshot_workflow.png`, `screenshot_execution.png`, `screenshot_history.png` показывают схему, успешно обработанные элементы и историю. `metrics.json` и `execution_summary.json` содержат измерения и SHA-256. Сравнение с 30 записями Scrapy подтверждает совпадение ключей и содержательных полей; первая страница запрашивалась n8n как `/page/1/`, а Scrapy как `/`, поэтому эти `source_url` различаются.

Проверены 3 успешных ответа страниц и 30 ответов авторов; сумма UTF-8 длин декодированных HTML-тел — 149 517 байт, без заголовков. Отдельная проверка robots.txt вернула 404. `network_requests=34` в `metrics.json` — число 33 успешных ответов плюс отдельная проверка robots, а не инструментально измеренное число сетевых попыток: повторы и возможные перенаправления не отслеживались. Настроен учебный User-Agent и до трёх попыток HTTP.

Отдельный управляемый тест #9 изменяет только в копии workflow адрес запроса на недоступный локальный 127.0.0.1:9: фактическое уведомление показано в `screenshot_notification.png`, ошибка n8n — в `screenshot_error_execution.png`, запись приёмника — в `notifications.jsonl`. Тест #10 с выключенным приёмником проверил отказ доставки. `error_test.json` содержит условия этих тестов. `validation_tests.json` фиксирует проверки отсутствующих полей, пустых тегов и невозможных календарных дат на коде экспортированных узлов.

Документация: [HTML](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.html/), [Loop Over Items](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.splitinbatches/), [история выполнений](https://docs.n8n.io/workflows/executions/all-executions/).
