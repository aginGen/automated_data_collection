import csv
import sys
from pathlib import Path


REQUIRED_FIELDS = ("title", "price_gbp", "rating", "url", "upc")


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        missing_fields = set(REQUIRED_FIELDS) - set(reader.fieldnames or ())
        if missing_fields:
            raise ValueError(f"Нет обязательных полей в {path.name}: {', '.join(sorted(missing_fields))}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"Пустой набор данных: {path.name}")
    if any(any(not row.get(field) or not row[field].strip() for field in REQUIRED_FIELDS) for row in rows):
        raise ValueError(f"Пустое обязательное поле: {path.name}")
    if len({row["upc"] for row in rows}) != len(rows):
        raise ValueError(f"Дублирующиеся UPC: {path.name}")
    try:
        if any(float(row["price_gbp"]) <= 0 or not 1 <= int(row["rating"]) <= 5 for row in rows):
            raise ValueError
    except ValueError:
        raise ValueError(f"Неверная цена или рейтинг: {path.name}") from None
    return rows


def main() -> int:
    directory = Path(__file__).resolve().parent
    try:
        python_rows = load_csv(directory / "books.csv")
        octoparse_rows = load_csv(directory / "octoparse_books.csv")
    except ValueError as exc:
        print(f"Ошибка сравнения: {exc}", file=sys.stderr)
        return 1

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

    python_fields = set(python_rows[0])
    octoparse_fields = set(octoparse_rows[0])
    only_python_fields = python_fields - octoparse_fields
    only_octoparse_fields = octoparse_fields - python_fields
    if only_python_fields:
        print("Дополнительные поля BeautifulSoup:", ", ".join(sorted(only_python_fields)))
    if only_octoparse_fields:
        print("Дополнительные поля Octoparse:", ", ".join(sorted(only_octoparse_fields)))

    total_differences = 0
    for field in REQUIRED_FIELDS:
        differences = 0
        for upc in shared:
            left, right = python_by_upc[upc][field], octoparse_by_upc[upc][field]
            if field == "price_gbp":
                left, right = float(left), float(right)
            elif field == "rating":
                left, right = int(left), int(right)
            differences += left != right
        print(f"Различий в {field}: {differences}")
        total_differences += differences

    return 1 if python_by_upc.keys() != octoparse_by_upc.keys() or total_differences else 0


if __name__ == "__main__":
    raise SystemExit(main())
