import argparse
import csv
import re
from pathlib import Path


FIELDS = ["title", "price_gbp", "rating", "url", "upc"]
RATINGS = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}


def clean_text(value: str) -> str:
    return " ".join(value.split())


def normalize(source: Path, destination: Path) -> list[dict]:
    unique = {}
    with source.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        required = {"Title1", "Price", "rating_raw", "Title_URL", "upc"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"В экспорте отсутствуют поля: {sorted(required - set(reader.fieldnames or []))}")
        for number, raw in enumerate(reader, start=2):
            match = re.search(r'class=[\"\']([^\"\']*\bstar-rating\b[^\"\']*)[\"\']', raw["rating_raw"])
            classes = match.group(1).split() if match else []
            rating = next((RATINGS[name] for name in classes if name in RATINGS), None)
            price = clean_text(raw["Price"]).removeprefix("£")
            row = {
                "title": clean_text(raw["Title1"]),
                "price_gbp": float(price),
                "rating": rating,
                "url": clean_text(raw["Title_URL"]),
                "upc": clean_text(raw["upc"]),
            }
            if any(value is None or value == "" for value in row.values()):
                raise ValueError(f"Пропущенное обязательное значение в строке {number}")
            if row["price_gbp"] <= 0 or not 1 <= row["rating"] <= 5:
                raise ValueError(f"Неверная цена или рейтинг в строке {number}")
            if row["upc"] in unique and unique[row["upc"]] != row:
                raise ValueError(f"Противоречивый дубликат UPC в строке {number}")
            unique.setdefault(row["upc"], row)
    rows = list(unique.values())
    if not rows:
        raise ValueError("Пустой экспорт Octoparse")
    with destination.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main() -> None:
    directory = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description='Очистить настоящий экспорт Octoparse, не обращаясь к сайту или books.csv.')
    parser.add_argument("--input", type=Path, default=directory / "octoparse_raw.csv")
    parser.add_argument("--output", type=Path, default=directory / "octoparse_books.csv")
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("Исходный экспорт и очищенный CSV должны быть разными файлами")
    rows = normalize(args.input, args.output)
    print(f"Octoparse: {len(rows)} уникальных строк, {len(FIELDS)} полей, пропуски 0.00%")
    print(f"Сохранено: {args.output}")


if __name__ == "__main__":
    main()
