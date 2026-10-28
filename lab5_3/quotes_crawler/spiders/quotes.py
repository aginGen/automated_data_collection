import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import scrapy
from quotes_crawler.items import QuoteItem

class QuotesSpider(scrapy.Spider):
    name = "quotes"
    allowed_domains = ["quotes.toscrape.com"]
    start_urls = ["https://quotes.toscrape.com/"]
    def __init__(self, run_id="final", max_pages=10, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state = {}  # SpiderState restores this when JOBDIR is configured.
        self.run_id = run_id
        self.max_pages = int(max_pages)
    async def start(self):
        for url in self.start_urls:
            yield scrapy.Request(url, callback=self.parse, errback=self.request_error)
    def parse(self, response):
        page = int(response.url.rstrip("/").split("/")[-1]) if "/page/" in response.url else 1
        self.crawler.stats.inc_value("list/pages")
        self.state.setdefault("authors", {})
        self.state.setdefault("pending", {})
        for card in response.css("div.quote"):
            context = dict(quote=card.css("span.text::text").get(), author=card.css("small.author::text").get(), tags=card.css("div.tags a.tag::text").getall(), source_url=response.url, list_page=page, collected_at=datetime.now(timezone.utc).isoformat())
            link = card.css("span a[href*='/author/']::attr(href)").get()
            if not link:
                self.crawler.stats.inc_value("dropped/missing_fields")
                continue
            url = response.urljoin(link).rstrip("/") + "/"
            context["author_url"] = url
            if url in self.state["authors"]:
                yield QuoteItem(**context, **self.state["authors"][url])
            elif url in self.state["pending"]:
                self.state["pending"][url].append(context)
            else:
                self.state["pending"][url] = []
                yield response.follow(url, callback=self.parse_item, errback=self.request_error, cb_kwargs={"author_url": url, "first_context": context})
        next_url = response.css("li.next a::attr(href)").get()
        if next_url and page < self.max_pages:
            yield response.follow(next_url, callback=self.parse, errback=self.request_error)
    def parse_item(self, response, author_url, first_context):
        details = dict(born_date=response.css("span.author-born-date::text").get(), born_location=response.css("span.author-born-location::text").get(), biography=" ".join(response.css("div.author-description ::text").getall()))
        self.crawler.stats.inc_value("author/pages")
        self.state["authors"][author_url] = details
        for context in [first_context] + self.state["pending"].pop(author_url, []):
            yield QuoteItem(**context, **details)
    def request_error(self, failure):
        self.crawler.stats.inc_value("errors/request")
        self.logger.error("Request failed: %s", failure)
        url = failure.request.cb_kwargs.get("author_url")
        if url:
            self.crawler.stats.inc_value("errors/affected_quotes", 1 + len(self.state.get("pending", {}).pop(url, [])))
    def closed(self, reason):
        stats = dict(self.crawler.stats.get_stats())
        stats["finish_reason"] = reason
        stats["finish_time"] = datetime.now(timezone.utc)
        if stats.get("start_time"):
            stats["duration_seconds"] = (stats["finish_time"] - stats["start_time"]).total_seconds()
        path = Path("data") / ("stats_" + self.run_id + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(stats, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
