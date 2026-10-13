import requests
import json
import os

API_KEY = os.environ["OPENWEATHER_API_KEY"]
CITY = "Пермь"

url = "https://api.openweathermap.org/data/2.5/weather"

params = {
    "q": CITY,
    "appid": API_KEY,
    "units": "metric",
    "lang": "ru"
}

response = requests.get(url, params=params)

if response.status_code == 200:
    data = response.json()
    
    temp = data["main"]["temp"]
    description = data["weather"][0]["description"]
    print(f"Погода: {temp}°C, {description}")
    
    filename = "weather.json"
    with open(filename, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)
        
    print(f"File: {filename}")
else:
    print(f"Error {response.status_code}: {response.text}")