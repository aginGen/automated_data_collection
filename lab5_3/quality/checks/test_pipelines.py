"""Проверка отклонений, нормализации, ключа и пакетной записи без сети."""
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from scrapy.statscollectors import MemoryStatsCollector
from scrapy.settings import Settings
from scrapy.exceptions import DropItem
from quotes_crawler.items import QuoteItem
from quotes_crawler.pipelines import ValidationPipeline, CleanPipeline, DeduplicatePipeline, SQLitePipeline
class Crawler:
    settings = Settings()
c = Crawler()
c.stats = MemoryStatsCollector(c)
valid = dict(quote=" A  quote ", author=" Test Author ", tags=[], author_url="https://example.org/a", born_date="March 14, 1879", born_location="here", biography="bio", source_url="https://example.org", list_page=1, collected_at=datetime.now(timezone.utc).isoformat())
v, clean, dedup = (x.from_crawler(c) for x in (ValidationPipeline, CleanPipeline, DeduplicatePipeline))
def dropped(pipeline, item):
    try: pipeline.process_item(item)
    except DropItem: return
    raise AssertionError("Expected DropItem")
a = QuoteItem(**valid); a["quote"] = ""; dropped(v, a)
a = QuoteItem(**valid); a["born_date"] = "not a date"; dropped(clean, a)
a = clean.process_item(v.process_item(QuoteItem(**valid)))
assert a["quote"] == "A quote" and a["born_date"] == "1879-03-14" and a["tags"] == []
dedup.process_item(a); dropped(dedup, a)
with tempfile.TemporaryDirectory() as d:
    c.settings.set("DATABASE_PATH", str(Path(d)/"test.db"))
    db = SQLitePipeline.from_crawler(c); db.open_spider(); db.process_item(a); db.close_spider()
    assert c.stats.get_value("database/rows_written") == 1 and c.stats.get_value("database/total_rows") == 1
assert c.stats.get_value("dropped/missing_fields") == 1
assert c.stats.get_value("dropped/invalid_value") == 1
assert c.stats.get_value("dropped/duplicate") == 1
print("OK: validation, date, optional tags, business-key duplicates, SQLite batch flush")

from quotes_crawler.tag_pipelines import ValidateRelation, DeduplicateRelation, StoreRelations
relation = QuoteItem(**valid, source_tag="science")
relation = clean.process_item(ValidateRelation.from_crawler(c).process_item(v.process_item(relation)))
rd = DeduplicateRelation.from_crawler(c); rd.process_item(relation); dropped(rd, relation)
assert c.stats.get_value("dropped/duplicate_relation") == 1
with tempfile.TemporaryDirectory() as d:
    c.settings.set("DATABASE_PATH", str(Path(d)/"relations.db"))
    store = StoreRelations.from_crawler(c); store.open_spider(); store.process_item(relation); store.close_spider()
    assert c.stats.get_value("database/unique_quotes") == 1 and c.stats.get_value("database/total_relations") == 1
print("OK: quote identity stays separate from quote-tag relation identity")

# Regression checks: missing strings, invalid types/dates/pages and malformed tag links.
for field in ("quote", "author", "author_url", "born_date", "born_location", "biography", "source_url", "collected_at"):
    item = QuoteItem(**valid); item[field] = "  "; dropped(v, item)
for field, value in (("author_url", 12), ("source_url", []), ("list_page", 0), ("list_page", -1), ("list_page", 1.5), ("list_page", True), ("collected_at", "2026-99-99"), ("collected_at", "2026-10-28T01:00:00"), ("tags", [None])):
    item = QuoteItem(**valid); item[field] = value; dropped(clean, item)
for value in ("", "   ", None):
    item = QuoteItem(**valid, source_tag=value); dropped(ValidateRelation.from_crawler(c), item)
item = QuoteItem(**valid, source_tag=123); dropped(ValidateRelation.from_crawler(c), item)
item = QuoteItem(**valid, source_tag="  SCIENCE  "); assert ValidateRelation.from_crawler(c).process_item(item)["source_tag"] == "science"
from quotes_crawler.spiders.tags import TagsSpider
from scrapy.http import HtmlResponse, Request
spider = TagsSpider(); spider.crawler = c
for bad in (None, "", "/tag/", "/missing/test/", "https://evil.example/tag/love/", "javascript:/tag/love/", "/tag/%2F/", "https://[bad", "https:/tag/love/", "//evil.example/tag/x/"):
    assert spider.tag_from_url(bad) is None
assert spider.tag_from_url("/tag/love/page/1/") == "love"
assert c.stats.get_value("tag/invalid_url") == 10
response = HtmlResponse(url="https://quotes.toscrape.com/", request=Request("https://quotes.toscrape.com/"), body=b'<span class="tag-item"><a class="tag" href="/tag/">bad</a><a class="tag" href="/tag/love/">love</a></span>', encoding="utf-8")
requests = list(spider.parse(response)); assert len(requests) == 1 and requests[0].cb_kwargs["source_tag"] == "love"
tag_response = HtmlResponse(url="https://quotes.toscrape.com/tag/love/", request=Request("https://quotes.toscrape.com/tag/love/"), body=b'<div class="quote"><div class="tags"><a class="tag" href="/tag/">bad</a><a class="tag" href="/tag/hope/">hope</a></div></div>', encoding="utf-8")
requests = list(spider.parse_tag(tag_response, "love", 1)); assert len(requests) == 1 and requests[0].cb_kwargs["source_tag"] == "hope"
# A second store against the same database must report zero actual inserts.
with tempfile.TemporaryDirectory() as d:
    path = str(Path(d)/"repeat.db")
    for expected_insert, expected_ignored in ((1,0), (0,1)):
        cc = Crawler(); cc.settings = Settings({"DATABASE_PATH":path}); cc.stats = MemoryStatsCollector(cc)
        store = StoreRelations.from_crawler(cc); store.open_spider(); store.process_item(relation); store.close_spider()
        assert cc.stats.get_value("database/relations_attempted") == 1
        assert cc.stats.get_value("database/relations_written") == expected_insert
        assert cc.stats.get_value("database/relations_ignored") == expected_ignored
print("OK: whitespace/type validation, malformed tag links, and persisted duplicate insert counts")
