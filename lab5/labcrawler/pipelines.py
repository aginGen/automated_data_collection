import hashlib
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem


REQUIRED = {
    "quote": ["quote", "author", "author_url", "birth_date", "birth_place", "biography"],
    "book": ["upc", "title", "price", "stock", "reviews", "category", "description", "rating", "url"],
}


def clean(value):
    return " ".join(str(value).split())


class BasePipeline:
    @classmethod
    def from_crawler(cls, crawler):
        instance = cls()
        instance.crawler = crawler
        return instance

    def reject(self, item, reason):
        self.crawler.stats.inc_value("dropped/" + reason)
        raise DropItem(f"{reason}: {ItemAdapter(item).asdict()}")


class ValidationPipeline(BasePipeline):
    def process_item(self, item):
        data = ItemAdapter(item)
        kind = data.get("kind")
        if kind not in REQUIRED or any(
            data.get(field) is None or data.get(field) == "" for field in REQUIRED.get(kind, [])
        ):
            self.reject(item, "missing_fields")
        return item


class CleaningPipeline(BasePipeline):
    def process_item(self, item):
        data = ItemAdapter(item)
        try:
            for field in REQUIRED[data["kind"]]:
                if isinstance(data[field], str):
                    data[field] = clean(data[field])
                    if not data[field]:
                        self.reject(item, "missing_fields")
            if data["kind"] == "quote":
                data["birth_date"] = datetime.strptime(data["birth_date"], "%B %d, %Y").date().isoformat()
                data["tags"] = sorted({clean(tag).casefold() for tag in data.get("tags", [])})
                business_key = data["author"].casefold() + "\n" + data["quote"]
                data["key"] = hashlib.sha256(business_key.encode("utf-8")).hexdigest()
            else:
                price = re.search(r"[-+]?\d+(?:\.\d+)?", data["price"])
                stock = re.search(r"\d+", data["stock"])
                if not price or not stock:
                    self.reject(item, "invalid_value")
                data["price"] = float(price.group())
                data["stock"] = int(stock.group())
                data["reviews"] = int(data["reviews"])
                ratings = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}
                data["rating"] = next(value for name, value in ratings.items() if name in data["rating"].split())
                data["upc"] = data["upc"].casefold()
                data["key"] = data["upc"]
                if data["price"] <= 0 or data["stock"] < 0 or not 1 <= data["rating"] <= 5:
                    self.reject(item, "invalid_value")
        except (ValueError, TypeError, StopIteration):
            self.reject(item, "invalid_value")
        return item


class DeduplicationPipeline(BasePipeline):
    def __init__(self):
        self.seen = None

    def process_item(self, item):
        spider = self.crawler.spider
        if self.seen is None:
            self.seen = set(spider.state.get("seen_business_keys", []))
        key = item["kind"] + ":" + item["key"]
        if key in self.seen:
            self.reject(item, "duplicate")
        self.seen.add(key)
        spider.state["seen_business_keys"] = sorted(self.seen)
        return item


class SQLitePipeline(BasePipeline):
    def open_spider(self):
        path = Path(self.crawler.settings.get("SQLITE_PATH", "data/crawl.db"))
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS quotes (
          key TEXT PRIMARY KEY, quote TEXT NOT NULL, author TEXT NOT NULL,
          tags TEXT NOT NULL, author_url TEXT NOT NULL, birth_date TEXT NOT NULL,
          birth_place TEXT NOT NULL, biography TEXT NOT NULL, url TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS books (
          key TEXT PRIMARY KEY, upc TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
          price REAL NOT NULL CHECK(price > 0), stock INTEGER NOT NULL,
          reviews INTEGER NOT NULL, category TEXT NOT NULL, description TEXT NOT NULL,
          rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5), url TEXT NOT NULL
        );
        """)
        self.buffers = {"quote": [], "book": []}
        self.batch_size = self.crawler.settings.getint("SQLITE_BATCH_SIZE", 50)

    def process_item(self, item):
        data = ItemAdapter(item).asdict()
        kind = data["kind"]
        if kind == "quote":
            self.buffers[kind].append((
                data["key"], data["quote"], data["author"], json.dumps(data["tags"], ensure_ascii=False),
                data["author_url"], data["birth_date"], data["birth_place"], data["biography"], data["url"],
            ))
        else:
            self.buffers[kind].append(tuple(data[name] for name in [
                "key", "upc", "title", "price", "stock", "reviews",
                "category", "description", "rating", "url",
            ]))
        if len(self.buffers[kind]) >= self.batch_size:
            self.flush(kind)
        return item

    def flush(self, kind):
        rows = self.buffers[kind]
        if not rows:
            return
        table, placeholders = ("quotes", 9) if kind == "quote" else ("books", 10)
        self.connection.executemany(
            f"INSERT OR REPLACE INTO {table} VALUES ({','.join('?' for _ in range(placeholders))})", rows,
        )
        self.connection.commit()
        self.crawler.stats.inc_value("database/written", len(rows))
        self.crawler.stats.inc_value("database/batches")
        rows.clear()

    def close_spider(self):
        try:
            for kind in self.buffers:
                self.flush(kind)
        finally:
            self.connection.close()
