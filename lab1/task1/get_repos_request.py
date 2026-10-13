import requests
import json

username = "onedanoken"
url = f"https://api.github.com/users/{username}/repos"

params = {
    "per_page": 30,
    "sort": "updated"
}

response = requests.get(url, params=params)

if response.status_code == 200:
    data = response.json()
    
    filename = f"{username}_repos.json"
    with open(filename, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)
        
    print(f"Found {len(data)} repos.")
    print(f"File: {filename}")
else:
    print(f"Error: {response.status_code}: {response.text}")