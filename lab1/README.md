# Лабораторная 1. HTTP-запросы

GitHub API: список публичных репозиториев. OpenWeather API: погода в Перми с API-ключом.

## Установка

Из папки `lab1`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Запуск

GitHub:

```powershell
cd task1
..\.venv\Scripts\python.exe get_repos_request.py
cd ..
```

OpenWeather:

```powershell
$taskKey = Read-Host "Ключ OpenWeather" -AsSecureString
$env:OPENWEATHER_API_KEY = [System.Net.NetworkCredential]::new("", $taskKey).Password
cd task2
..\.venv\Scripts\python.exe get_weather_request.py
cd ..
```

Ключ действует в текущем терминале. Его не нужно записывать в код или публиковать.
Скрипты используют requests; при ошибке соединения новый ответ не будет получен.

## Файлы

- `task1/get_repos_request.py` и `task1/onedanoken_repos.json` - запрос и сохранённый ответ GitHub.
- `task2/get_weather_request.py` и `task2/weather.json` - запрос и сохранённый ответ OpenWeather.
- [lab1.ipynb](lab1.ipynb) - пошаговый разбор сохранённых результатов.
- [PDF-отчёт](report.pdf) - отчёт.

Для показа откройте блокнот с Python из `.venv`. Его ячейки читают сохранённые файлы и не отправляют запросы.
Новый запрос выполняется отдельной командой выше.

Редактируемый исходник отчёта: [report.md](report.md).
