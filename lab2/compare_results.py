import csv
from pathlib import Path


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    if not rows:
        raise ValueError(f"Пустой набор данных: {path.name}")
    if any(not row.get("upc") for row in rows):
        raise ValueError(f"Отсутствует UPC: {path.name}")
    if len({row["upc"] for row in rows}) != len(rows):
        raise ValueError(f"Дублирующиеся UPC: {path.name}")
    for row in rows:
        if float(row["price_gbp"]) <= 0 or not 1 <= int(row["rating"]) <= 5:
            raise ValueError(f"Неверная цена или рейтинг: {path.name}")
    return rows


def main() -> None:
    directory = Path(__file__).resolve().parent
    python_rows = load_csv(directory / "books.csv")
    octoparse_rows = load_csv(directory / "octoparse_books.csv")
    for name, rows in (("BeautifulSoup", python_rows), ("Octoparse", octoparse_rows)):
        values = [value for row in rows for value in row.values()]
        missing = sum(value is None or value.strip() == "" for value in values)
        print(f"{name}: {len(rows)} строк, {len(rows[0])} полей, пропуски {missing / len(values):.2%}")
        print("Поля:", ", ".join(rows[0]))

    python_by_upc = {row["upc"]: row for row in python_rows}
    octoparse_by_upc = {row["upc"]: row for row in octoparse_rows}
    shared = python_by_upc.keys() & octoparse_by_upc.keys()
    print(f"Общих UPC: {len(shared)}")
    print(f"Только BeautifulSoup: {len(python_by_upc.keys() - shared)}")
    print(f"Только Octoparse: {len(octoparse_by_upc.keys() - shared)}")
    fields = [field for field in python_rows[0] if field in octoparse_rows[0]]
    for field in fields:
        differences = 0
        for upc in shared:
            left, right = python_by_upc[upc][field], octoparse_by_upc[upc][field]
            if field == "price_gbp":
                left, right = float(left), float(right)
            elif field == "rating":
                left, right = int(left), int(right)
            differences += left != right
        print(f"Различий в {field}: {differences}")


if __name__ == "__main__":
    main()
