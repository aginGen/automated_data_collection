# Лабораторная 1. Отчёт

Задачи: получить репозитории пользователя GitHub и выполнить запрос к API с авторизацией.
Во второй задаче выбран OpenWeather.

## Запросы

| Источник | Метод и адрес | Параметры | Авторизация |
|---|---|---|---|
| GitHub | GET https://api.github.com/users/onedanoken/repos | per_page=30, sort=updated | Для публичных репозиториев не требуется |
| OpenWeather | GET https://api.openweathermap.org/data/2.5/weather | q=Пермь, units=metric, lang=ru, appid | API-ключ из OPENWEATHER_API_KEY |

При статусе 200 скрипт разбирает JSON через `response.json()` и сохраняет его через `json.dump`.
Другой HTTP-статус выводится как ошибка. Заголовок `Content-Type` описывает формат ответа;
в этих двух скриптах отдельная проверка этого заголовка не реализована.

## GitHub

[get_repos_request.py](task1/get_repos_request.py) получает массив объектов репозиториев.
В [сохранённом ответе](task1/onedanoken_repos.json) 15 объектов.
Для просмотра в блокноте выбраны название, ссылка и число звёзд.
Параметр per_page=30 ограничивает размер одной порции, а не задаёт точное число объектов.

## OpenWeather

[get_weather_request.py](task2/get_weather_request.py) получает вложенный JSON с погодой.
Температура берётся из `main.temp`, описание - из `weather[0].description`.
В [weather.json](task2/weather.json) сохранён пример ответа для Перми.
Это сохранённая погода, а не показание на момент открытия отчёта.

API-ключ читается из переменной окружения. Значение ключа в файлах работы не хранится.
Без заданного ключа новый запрос к OpenWeather запустить нельзя.

## Результат

Оба ответа сохранены в JSON. Пошаговый просмотр находится в [lab1.ipynb](lab1.ipynb),
команды нового запуска - в [README](README.md).

Источники: [GitHub REST API](https://docs.github.com/en/rest/repos/repos#list-repositories-for-a-user),
[OpenWeather Current Weather](https://openweathermap.org/api/current).
