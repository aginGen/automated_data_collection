import argparse
import csv
from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import sqlite3

def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or (list(rows[0]) if rows else [])
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


ROOT = Path(__file__).resolve().parents[1]

REQUIRED = {
    "quotes": ["key", "quote", "author", "birth_date", "birth_place", "biography", "author_url"],
    "books": ["key", "upc", "title", "price", "stock", "reviews", "category", "description", "rating", "url"],
}


def analyze(database: Path = ROOT / "data/crawl.db", directory: Path = ROOT / "quality",
            label: str = "current") -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    report = {"rows": 0, "tables": {}, "required_empty_share": 0, "aggregates": {}}
    completeness = []
    exported = []
    with closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        for table in REQUIRED:
            rows = [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY key")]
            columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
            empty_records = sum(any(row[name] is None or str(row[name]).strip() == "" for name in REQUIRED[table]) for row in rows)
            unique = len({row["key"] for row in rows})
            complete = {
                name: round(sum(row[name] is not None and str(row[name]).strip() != "" for row in rows) / max(len(rows), 1) * 100, 2)
                for name in columns
            }
            info = {
                "rows": len(rows), "unique_keys": unique, "duplicates": len(rows) - unique,
                "required_empty_rows": empty_records, "completeness_percent": complete,
                "sql_types": {row[1]: row[2] for row in connection.execute(f"PRAGMA table_info({table})")},
            }
            report["tables"][table] = info
            report["rows"] += len(rows)
            completeness.extend({"table": table, "field": field, "completeness_percent": value}
                                for field, value in complete.items())
            write_csv(directory / f"{table}.csv", rows, columns)
            exported.extend({"kind": "quote" if table == "quotes" else "book", **row} for row in rows)
        report["required_empty_share"] = sum(t["required_empty_rows"] for t in report["tables"].values()) / max(report["rows"], 1)
        report["aggregates"]["quotes_by_author"] = [dict(row) for row in connection.execute(
            "SELECT author, COUNT(*) AS quotes FROM quotes GROUP BY author ORDER BY quotes DESC, author")]
        report["aggregates"]["price_by_category"] = [dict(row) for row in connection.execute(
            "SELECT category, COUNT(*) AS books, ROUND(AVG(price),2) AS average_price FROM books GROUP BY category ORDER BY books DESC")]
        tags = Counter()
        for row in connection.execute("SELECT tags FROM quotes"):
            tags.update(json.loads(row["tags"]))
        report["aggregates"]["quotes_by_tag"] = [{"tag": tag, "quotes": count} for tag, count in tags.most_common()]
        report["business_rule_violations"] = {
            "nonpositive_price": connection.execute("SELECT COUNT(*) FROM books WHERE price <= 0").fetchone()[0],
            "invalid_rating": connection.execute("SELECT COUNT(*) FROM books WHERE rating NOT BETWEEN 1 AND 5").fetchone()[0],
            "negative_stock_or_reviews": connection.execute("SELECT COUNT(*) FROM books WHERE stock < 0 OR reviews < 0").fetchone()[0],
            "empty_quotes": connection.execute("SELECT COUNT(*) FROM quotes WHERE LENGTH(TRIM(quote)) = 0").fetchone()[0],
        }
    stats = []
    for path in sorted((ROOT / "data").glob("stats_*.json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        stats.append({
            "run": path.stem.removeprefix("stats_"), "items": run.get("item_scraped_count", 0),
            "written": run.get("database/written", 0), "list_pages": run.get("list_pages", 0),
            "duration_s": round(run.get("elapsed_time_seconds", 0), 4),
            "requests": run.get("network/request_count", 0),
            "response_bytes": run.get("network/response_body_bytes", 0),
            "retries": run.get("retry/count", 0), "cache_store": run.get("httpcache/store", 0),
            "cache_hit": run.get("httpcache/hit", 0), "dupefilter_filtered": run.get("dupefilter/filtered", 0),
            "dropped_missing": run.get("dropped/missing_fields", 0),
            "dropped_invalid": run.get("dropped/invalid_value", 0),
            "dropped_duplicate": run.get("dropped/duplicate", 0),
            "response_codes": {key.rsplit("/",1)[-1]: value for key,value in run.items()
                               if key.startswith("downloader/response_status_count/")},
            "errors": run.get("log_count/ERROR", 0),
        })
    report["runs"] = stats
    write_json(directory / f"{label}.json", report)
    write_csv(directory / "completeness.csv", completeness)
    (ROOT / "data/items.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in exported) + "\n", encoding="utf-8",
    )
    print(json.dumps({"rows": report["rows"], "tables": {k:v["rows"] for k,v in report["tables"].items()},
                      "required_empty_share": report["required_empty_share"]}, ensure_ascii=False))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Качество данных SQLite и выгрузка собранных записей.')
    parser.add_argument("--database", type=Path, default=ROOT / "data/crawl.db")
    parser.add_argument("--label", default="current")
    args = parser.parse_args()
    analyze(args.database, label=args.label)
