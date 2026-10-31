import json
import os
import sys
from pathlib import Path

import requests


def main() -> int:
    api_key = os.environ.get("OPENWEATHER_API_KEY")
    if not api_key:
        print("Не задан OPENWEATHER_API_KEY.", file=sys.stderr)
        return 1

    city = "Пермь"
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {"q": city, "appid": api_key, "units": "metric", "lang": "ru"}

    try:
        response = requests.get(url, params=params, timeout=20)
    except requests.RequestException:
        print("Ошибка сети при запросе OpenWeather.", file=sys.stderr)
        return 1

    if response.status_code != 200:
        print(f"OpenWeather вернул HTTP {response.status_code}.", file=sys.stderr)
        return 1

    try:
        data = response.json()
        temp = data["main"]["temp"]
        description = data["weather"][0]["description"]
    except (ValueError, KeyError, IndexError, TypeError):
        print("OpenWeather вернул некорректные данные.", file=sys.stderr)
        return 1

    filename = "weather.json"
    output = Path(__file__).resolve().parent / filename
    with output.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)

    print(f"Погода: {temp}°C, {description}")
    print(f"File: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
