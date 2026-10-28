import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem

class Base:
    @classmethod
    def from_crawler(cls, crawler):
        obj = cls()
        obj.crawler = crawler
        return obj

class ValidationPipeline(Base):
    # Empty tags are valid on this source; all listed fields must be present.
    required = ("quote", "author", "author_url", "born_date", "born_location", "biography", "source_url", "list_page", "collected_at")
    def process_item(self, item):
        a = ItemAdapter(item)
        missing = [k for k in self.required if a.get(k) is None or (isinstance(a.get(k), str) and not a[k].strip())]
        if missing:
            self.crawler.stats.inc_value("dropped/missing_fields")
            raise DropItem("Missing: " + ", ".join(missing))
        return item

class CleanPipeline(Base):
    def process_item(self, item):
        a = ItemAdapter(item)
        try:
            for k in ("quote", "author", "author_url", "born_location", "biography", "source_url"):
                if not isinstance(a[k], str): raise ValueError(f"{k} must be text")
                a[k] = " ".join(a[k].split())
                if not a[k]: raise ValueError(f"{k} is empty")
            tags = a.get("tags", [])
            if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
                raise ValueError("tags must be a list of strings")
            a["tags"] = [" ".join(t.split()).lower() for t in tags if t.strip()]
            if not a["tags"]: self.crawler.stats.inc_value("quality/empty_tags")
            if not isinstance(a["born_date"], str): raise ValueError("born_date must be text")
            a["born_date"] = datetime.strptime(" ".join(a["born_date"].split()), "%B %d, %Y").date().isoformat()
            page = a["list_page"]
            if isinstance(page, bool) or not (isinstance(page, int) or isinstance(page, str) and page.strip().isdigit()):
                raise ValueError("list_page must be a positive integer")
            a["list_page"] = int(page)
            if a["list_page"] < 1: raise ValueError("list_page must be positive")
            if not isinstance(a["collected_at"], str): raise ValueError("collected_at must be ISO datetime")
            stamp = datetime.fromisoformat(a["collected_at"].strip().replace("Z", "+00:00"))
            if stamp.tzinfo is None: raise ValueError("collected_at must include timezone")
            a["collected_at"] = stamp.isoformat()
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            self.crawler.stats.inc_value("dropped/invalid_value")
            raise DropItem(str(exc))
        a["business_key"] = hashlib.sha256((a["author"].lower() + "\n" + a["quote"]).encode("utf-8")).hexdigest()
        return item

class DeduplicatePipeline(Base):
    def __init__(self): self.seen = set()
    def process_item(self, item):
        key = ItemAdapter(item)["business_key"]
        if key in self.seen:
            self.crawler.stats.inc_value("dropped/duplicate")
            raise DropItem("Duplicate business key")
        self.seen.add(key)
        return item

class SQLitePipeline(Base):
    columns = ("business_key", "quote", "author", "tags_json", "author_url", "born_date", "born_location", "biography", "source_url", "list_page", "collected_at")
    def open_spider(self):
        path = Path(self.crawler.settings.get("DATABASE_PATH"))
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS quotes (business_key TEXT PRIMARY KEY, quote TEXT NOT NULL, author TEXT NOT NULL, tags_json TEXT NOT NULL, author_url TEXT NOT NULL, born_date TEXT NOT NULL, born_location TEXT NOT NULL, biography TEXT NOT NULL, source_url TEXT NOT NULL, list_page INTEGER NOT NULL, collected_at TEXT NOT NULL)")
        self.batch = []
    def process_item(self, item):
        a = ItemAdapter(item)
        self.batch.append(tuple(json.dumps(a["tags"], ensure_ascii=False) if k == "tags_json" else a[k] for k in self.columns))
        if len(self.batch) >= 20: self.flush()
        return item
    def flush(self):
        if self.batch:
            self.db.executemany("INSERT OR REPLACE INTO quotes VALUES (?,?,?,?,?,?,?,?,?,?,?)", self.batch)
            self.db.commit()
            self.crawler.stats.inc_value("database/rows_written", len(self.batch))
            self.batch.clear()
    def close_spider(self):
        self.flush()
        self.crawler.stats.set_value("database/total_rows", self.db.execute("SELECT count(*) FROM quotes").fetchone()[0])
        self.db.close()
