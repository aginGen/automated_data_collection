import re
from dataclasses import dataclass
from decimal import Decimal
from unicodedata import category as unicode_category, normalize

from pydantic import ValidationError

from .contract import Book, Rate


STARS = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}


def normal_text(value):
    cleaned = "".join(ch for ch in normalize("NFKC", value or "") if unicode_category(ch) != "Cf")
    return " ".join(cleaned.split())


def parse_book(row):
    key = int(row["source_id"]) if row["source_id"] is not None else None
    price = re.fullmatch(r"£\s*(\d+(?:\.\d{1,2})?)", normal_text(row["price_raw"]))
    stock = normal_text(row["stock_raw"]).casefold()
    return {
        **row,
        "source_id": key,
        "business_key": f"books:{key}",
        "title": normal_text(row["title_raw"]),
        "category": normal_text(row["category_raw"]),
        "price_pence": int(Decimal(price[1]) * 100) if price else None,
        "currency": "GBP",
        "rating": next((STARS[name] for name in row["rating_raw"] or [] if name in STARS), None),
        "in_stock": (True if stock == "in stock" else False if stock == "out of stock" else None),
    }


def parse_rate(row):
    scaled = Decimal(row["value_raw"]) * 10000
    if not scaled.is_finite() or scaled != scaled.to_integral_value():
        raise ValueError("курс не представлен с точностью до 0,0001 ₽")
    return {**row, "business_key": f"{row['currency']}:{row['rate_date']}", "rub_x10000": int(scaled)}


@dataclass
class CleanData:
    books: list[Book]
    rates: list[Rate]
    rejects: list[dict]
    raw_records: int
    valid_before_dedup: int
    duplicate_count: int
    protocol: list[dict]


def normalize_and_validate(book_rows, rate_rows):
    rejects = []
    products = {}
    rates = {}
    groups = (
        (book_rows, Book, parse_book, products),
        (rate_rows, Rate, parse_rate, rates),
    )
    total = len(book_rows) + len(rate_rows)
    typed_count = 0
    changed_count = 0
    valid_count = 0
    for rows, model, parse, groups_by_key in groups:
        for row in rows:
            try:
                typed = parse(row)
                typed_count += 1
                changed_count += typed != row
                entry = model.model_validate(typed)
            except ValidationError as exc:
                reasons = [
                    {"field": ".".join(map(str, issue["loc"])) or "record", "reason": issue["msg"]}
                    for issue in exc.errors(include_url=False)
                ]
                rejects.append({"stage": "contract", "reasons": reasons, "raw": row})
            except (ArithmeticError, TypeError, ValueError) as exc:
                rejects.append({"stage": "types", "reasons": [{"field": "record", "reason": str(exc)}], "raw": row})
            else:
                valid_count += 1
                old = groups_by_key.get(entry.business_key)
                if old is None or entry.collected_at >= old.collected_at:
                    groups_by_key[entry.business_key] = entry
    retained = len(products) + len(rates)
    protocol = [
        {"step": "normalize_and_type", "before": total, "after": typed_count, "changed": changed_count,
         "removed": total - typed_count},
        {"step": "validate", "before": typed_count, "after": valid_count, "changed": 0,
         "removed": typed_count - valid_count},
        {"step": "deduplicate", "before": valid_count, "after": retained, "changed": 0,
         "removed": valid_count - retained},
    ]
    return CleanData(
        books=sorted(products.values(), key=lambda item: item.source_id),
        rates=sorted(rates.values(), key=lambda rate: rate.rate_date),
        rejects=rejects,
        raw_records=total,
        valid_before_dedup=valid_count,
        duplicate_count=valid_count - retained,
        protocol=protocol,
    )
