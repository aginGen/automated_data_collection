import sqlite3
from pathlib import Path

from .files import PROJECT, utc_now


PRODUCT_FIELDS = (
    "business_key", "source", "source_id", "title", "category", "currency",
    "price_pence", "rating", "in_stock", "product_url", "source_url", "collected_at",
    "updated_at", "parser_version",
)
RATE_FIELDS = (
    "business_key", "source", "currency", "rate_date", "nominal", "rub_x10000",
    "quote_field", "source_url", "collected_at", "updated_at", "parser_version",
)


def open_warehouse(path: Path | str):
    if isinstance(path, Path):
        path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript((PROJECT / "db" / "schema.sql").read_text(encoding="utf-8"))
    return db


def write_items(db, table, fields, compared, entries):
    names = ", ".join(fields)
    params = ", ".join(":" + name for name in fields)
    updates = ", ".join(f"{field} = excluded.{field}" for field in fields if field != "business_key")
    changed = " OR ".join(f"{table}.{name} IS NOT excluded.{name}" for name in compared)
    sql = (
        f"INSERT INTO {table} ({names}) VALUES ({params}) "
        f"ON CONFLICT(business_key) DO UPDATE SET {updates} WHERE {changed}"
    )
    existing = {row[0] for row in db.execute(f"SELECT business_key FROM {table}")}
    updated_at = utc_now()
    stats = {"inserted": 0, "updated": 0, "unchanged": 0}
    for entry in entries:
        values = entry.model_dump(mode="json")
        values["updated_at"] = updated_at
        cursor = db.execute(sql, values)
        if cursor.rowcount == 0:
            stats["unchanged"] += 1
        elif entry.business_key in existing:
            stats["updated"] += 1
        else:
            stats["inserted"] += 1
    return stats


def load_warehouse(db, books, rates):
    with db:
        product_stats = write_items(
            db, "products", PRODUCT_FIELDS,
            ("title", "category", "price_pence", "rating", "in_stock", "product_url"), books
        )
        rate_stats = write_items(db, "exchange_rates", RATE_FIELDS, ("nominal", "rub_x10000"), rates)
        db.execute("CREATE TEMP TABLE IF NOT EXISTS current_product_keys (business_key TEXT PRIMARY KEY)")
        db.execute("DELETE FROM current_product_keys")
        db.executemany("INSERT INTO current_product_keys VALUES (?)", [(book.business_key,) for book in books])
        removed = db.execute(
            "DELETE FROM products WHERE NOT EXISTS "
            "(SELECT 1 FROM current_product_keys k WHERE k.business_key = products.business_key)"
        ).rowcount
    product_stats["removed"] = removed
    product_stats["count"] = db.execute("SELECT count(*) FROM products").fetchone()[0]
    product_stats["history"] = db.execute("SELECT count(*) FROM product_history").fetchone()[0]
    return {"products": product_stats, "rates": rate_stats}


def stored_snapshot(db):
    return dict(db.execute("SELECT business_key, updated_at FROM products ORDER BY business_key"))


def demonstrate_upsert(data):
    db = open_warehouse(":memory:")
    try:
        first = load_warehouse(db, data.books, data.rates)
        before = stored_snapshot(db)
        second = load_warehouse(db, data.books, data.rates)
        after = stored_snapshot(db)
        edited_keys = [book.business_key for book in data.books[:2]]
        edited = [
            book.model_copy(update={"price_pence": book.price_pence + 100 + index})
            if index < 2 else book for index, book in enumerate(data.books)
        ]
        third = load_warehouse(db, edited, data.rates)
        changed_keys = [
            row[0] for row in db.execute(
                "SELECT business_key FROM product_history WHERE change_kind = 'update' ORDER BY business_key"
            )
        ]
        constraint_checks = {}
        for name, sql in (
            ("check_price", "UPDATE products SET price_pence = -1"),
            ("not_null_title", "UPDATE products SET title = NULL"),
            ("unique_key", "INSERT INTO products SELECT * FROM products LIMIT 1"),
        ):
            try:
                with db:
                    db.execute(sql)
            except sqlite3.IntegrityError:
                constraint_checks[name] = "rejected"
            else:
                raise AssertionError(f"Ограничение не сработало: {name}")
        if before != after or second["products"]["updated"] or set(changed_keys) != set(edited_keys):
            raise AssertionError("Идемпотентность не подтверждена")
        return {"first": first, "second": second, "third": third, "updated_at_preserved": before == after,
                "changed_keys": sorted(changed_keys), "constraint_checks": constraint_checks}
    finally:
        db.close()
