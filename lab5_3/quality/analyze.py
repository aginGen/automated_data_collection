"""Read-only analysis of the submitted SQLite database and crawl statistics."""

import argparse
from collections import Counter
import csv
from datetime import date
import hashlib
import json
from pathlib import Path
import sqlite3

LAB = Path(__file__).resolve().parents[1]
REQUIRED = ("business_key", "quote", "author", "author_url", "born_date",
            "born_location", "biography", "source_url", "list_page", "collected_at")


def normalize(value):
    return " ".join(str(value).split())


def is_empty(value):
    return value is None or (isinstance(value, str) and not value.strip())


def read_rows(database, table="quotes"):
    if table not in ("quotes", "quote_tags"):
        raise ValueError("Unknown table")
    with sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        key = "business_key" if table == "quotes" else "business_key, source_tag"
        return [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY {key}")]


def summarize(rows, scope="quotes.toscrape.com:all:variant3"):
    n = len(rows)
    fields = list(rows[0]) if rows else list(REQUIRED) + ["tags_json"]
    completeness = {}
    for field in fields:
        present = sum(not is_empty(row.get(field)) for row in rows)
        if field == "tags_json":
            present = sum(bool(json.loads(row.get(field) or "[]")) for row in rows)
        completeness[field] = {"filled": present, "empty": n - present,
                               "percent": round(100 * present / n, 4) if n else 0.0}
    missing_cells = sum(is_empty(row.get(field)) for row in rows for field in REQUIRED)
    missing_rows = sum(any(is_empty(row.get(field)) for field in REQUIRED) for row in rows)
    authors = Counter(row["author"] for row in rows)
    tags = Counter(tag for row in rows for tag in json.loads(row.get("tags_json") or "[]"))
    born_centuries = Counter()
    invalid_dates = 0
    for row in rows:
        try:
            born_centuries[str((date.fromisoformat(row["born_date"]).year - 1) // 100 + 1)] += 1
        except (ValueError, TypeError, KeyError):
            invalid_dates += 1
    keys = [row["business_key"] for row in rows]
    pairs = [(normalize(row["author"]).lower(), normalize(row["quote"])) for row in rows]
    invalid_keys = sum(hashlib.sha256((author + "\n" + quote).encode("utf-8")).hexdigest() != key
                       for (author, quote), key in zip(pairs, keys))
    return {
        "schema_version": 1, "scope": scope, "rows": n,
        "unique_keys": len(set(keys)), "unique_author_quote_pairs": len(set(pairs)),
        "duplicates": n - len(set(pairs)), "invalid_business_keys": invalid_keys,
        "invalid_birth_dates": invalid_dates,
        "list_pages": sorted({row["list_page"] for row in rows}),
        "authors_count": len(authors), "required_fields": list(REQUIRED),
        "required_empty_cells": missing_cells,
        "required_empty_share": missing_cells / (n * len(REQUIRED)) if n else 0.0,
        "rows_with_missing_required": missing_rows,
        "rows_with_missing_required_share": missing_rows / n if n else 0.0,
        "completeness": completeness,
        "quotes_by_author": dict(authors.most_common()),
        "quotes_by_tag": dict(tags.most_common()),
        "quotes_by_author_birth_century": dict(sorted(born_centuries.items())),
        "empty_tags_note": "Пустой список тегов допустим в источнике; это не пропуск обязательного скалярного поля.",
    }


def run_statistics(data_dir):
    result = []
    for path in sorted(Path(data_dir).glob("stats_*.json")):
        stats = json.loads(path.read_text(encoding="utf-8-sig"))
        # Also accepts a wrapper with a 'stats' member for future exporters.
        values = stats.get("stats", stats)
        result.append({
            "file": path.name,
            "items": values.get("item_scraped_count", 0),
            "db_written": values.get("database/rows_written", values.get("database/written", values.get("db/written", 0))),
            "relations_written": values.get("database/relations_written", 0),
            "relations_attempted": values.get("database/relations_attempted", 0),
            "relations_ignored": values.get("database/relations_ignored", 0),
            "elapsed_seconds": values.get("duration_seconds", values.get("elapsed_time_seconds")),
            "finish_reason": values.get("finish_reason"),
            "responses": {key.rsplit("/", 1)[-1]: value for key, value in values.items()
                          if key.startswith("downloader/response_status_count/")},
            "retries": values.get("retry/count", 0),
            "request_bytes": values.get("downloader/request_bytes", 0),
            "response_bytes": values.get("downloader/response_bytes", 0),
            "downloader_requests": values.get("downloader/request_count", 0),
            "network_requests": values.get("network/request_count", values.get("downloader/request_count", 0) - values.get("httpcache/hit", 0)),
            "httpcache_hit": values.get("httpcache/hit", 0),
            "httpcache_store": values.get("httpcache/store", 0),
            "dropped": {key: value for key, value in values.items() if key.startswith("dropped/")},
        })
    return result


def write_report(database, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    summary = summarize(read_rows(database))
    relations = read_rows(database, "quote_tags")
    summary["tag_associations"] = len(relations)
    summary["unique_tag_associations"] = len({(row["business_key"], row["source_tag"]) for row in relations})
    summary["tags_discovered"] = len({row["source_tag"] for row in relations})
    keys = {row["business_key"] for row in read_rows(database)}
    summary["orphan_tag_associations"] = sum(row["business_key"] not in keys for row in relations)
    summary["association_note"] = "Связи цитата-тег не увеличивают число уникальных цитат."
    summary["database"] = str(Path(database).name)
    summary["runs"] = run_statistics(LAB / "data")
    (output / "current.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (output / "completeness.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["field", "filled", "empty", "percent"])
        writer.writerows([field, *info.values()] for field, info in summary["completeness"].items())
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=LAB / "data" / "crawl.db")
    parser.add_argument("--output", type=Path, default=LAB / "quality")
    args = parser.parse_args()
    summary = write_report(args.db, args.output)
    print(json.dumps({key: summary[key] for key in ("rows", "unique_keys", "duplicates", "required_empty_share")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
