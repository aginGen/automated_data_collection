"""Relations use a separate key; author+quote remains the quote business key."""
import json
import sqlite3
from pathlib import Path
from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem
from quotes_crawler.pipelines import Base

class ValidateRelation(Base):
    def process_item(self, item):
        a=ItemAdapter(item)
        tag = a.get("source_tag")
        if tag is None or isinstance(tag, str) and not tag.strip():
            self.crawler.stats.inc_value("dropped/missing_fields")
            raise DropItem("Missing source tag")
        if not isinstance(tag, str):
            self.crawler.stats.inc_value("dropped/invalid_value")
            raise DropItem("Source tag must be text")
        a["source_tag"] = " ".join(tag.split()).lower()
        return item

class DeduplicateRelation(Base):
    def __init__(self): self.seen=set()
    def process_item(self,item):
        a=ItemAdapter(item); key=(a["business_key"],a["source_tag"].strip().lower())
        a["source_tag"]=key[1]
        if key in self.seen:
            self.crawler.stats.inc_value("dropped/duplicate_relation")
            raise DropItem("Duplicate quote-tag relation")
        self.seen.add(key); return item

class StoreRelations(Base):
    def open_spider(self):
        path=Path(self.crawler.settings.get("DATABASE_PATH")); path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS quotes (business_key TEXT PRIMARY KEY, quote TEXT NOT NULL, author TEXT NOT NULL, tags_json TEXT NOT NULL, author_url TEXT NOT NULL, born_date TEXT NOT NULL, born_location TEXT NOT NULL, biography TEXT NOT NULL, source_url TEXT NOT NULL, list_page INTEGER NOT NULL, collected_at TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS quote_tags (business_key TEXT NOT NULL, source_tag TEXT NOT NULL, PRIMARY KEY(business_key,source_tag), FOREIGN KEY(business_key) REFERENCES quotes(business_key))")
        self.batch=[]
    def process_item(self,item):
        a=ItemAdapter(item)
        quote=tuple(json.dumps(a["tags"],ensure_ascii=False) if k=="tags_json" else a[k] for k in ("business_key","quote","author","tags_json","author_url","born_date","born_location","biography","source_url","list_page","collected_at"))
        self.batch.append((quote,(a["business_key"],a["source_tag"])))
        if len(self.batch)>=20: self.flush()
        return item
    def flush(self):
        if self.batch:
            self.db.executemany("INSERT OR IGNORE INTO quotes VALUES (?,?,?,?,?,?,?,?,?,?,?)",[x[0] for x in self.batch])
            attempted = len(self.batch)
            cursor = self.db.executemany("INSERT OR IGNORE INTO quote_tags VALUES (?,?)", [x[1] for x in self.batch])
            inserted = cursor.rowcount
            self.db.commit()
            self.crawler.stats.inc_value("database/relations_attempted", attempted)
            self.crawler.stats.inc_value("database/relations_written", inserted)
            self.crawler.stats.inc_value("database/relations_ignored", attempted - inserted)
            self.batch.clear()
    def close_spider(self):
        self.flush()
        self.crawler.stats.set_value("database/unique_quotes",self.db.execute("SELECT count(*) FROM quotes").fetchone()[0])
        self.crawler.stats.set_value("database/total_relations",self.db.execute("SELECT count(*) FROM quote_tags").fetchone()[0]); self.db.close()
