import json
import sys
from pathlib import Path

import requests


def main() -> int:
    username = "onedanoken"
    url = f"https://api.github.com/users/{username}/repos"
    params = {"per_page": 30, "sort": "updated"}

    try:
        response = requests.get(url, params=params, timeout=20)
    except requests.RequestException:
        print("Ошибка сети при запросе GitHub.", file=sys.stderr)
        return 1

    if response.status_code != 200:
        print(f"GitHub вернул HTTP {response.status_code}.", file=sys.stderr)
        return 1

    try:
        data = response.json()
    except ValueError:
        print("GitHub вернул некорректный JSON.", file=sys.stderr)
        return 1

    filename = f"{username}_repos.json"
    output = Path(__file__).resolve().parent / filename
    with output.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)

    print(f"Found {len(data)} repos.")
    print(f"File: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
