import json
from datetime import datetime, timezone
from pathlib import Path

import scrapy

from labcrawler.items import CollectedItem

class QuotesSpider(scrapy.Spider):
    name = "quotes"
    allowed_domains = ["quotes.toscrape.com"]
    start_urls = ["https://quotes.toscrape.com/page/1/"]

    def __init__(self, run_id="quotes", max_pages="15", **kwargs):
        super().__init__(**kwargs)
        self.run_id = run_id
        self.max_pages = int(max_pages)
        self.state = {}

    async def start(self):
        for url in self.start_urls:
            yield scrapy.Request(url, callback=self.parse, errback=self.handle_error,
                                 dont_filter=False)

    def parse(self, response):
        page_number = int(response.url.rstrip("/").split("/")[-1])
        self.crawler.stats.inc_value("list_pages")
        for card in response.css(".quote"):
            text = card.css(".text::text").get()
            author = card.css(".author::text").get()
            author_link = card.css("a[href*='/author/']::attr(href)").get()
            context = {"quote": text, "author": author,
                       "tags": card.css(".tags .tag::text").getall(), "url": response.url}
            if not author_link:
                yield CollectedItem(kind="quote", **context)
                continue

            yield response.follow(author_link, callback=self.parse_item,
                                  cb_kwargs={"quote_data": context},
                                  errback=self.handle_error, dont_filter=True)
        next_link = response.css("li.next a::attr(href)").get()
        if next_link and page_number < self.max_pages:
            yield response.follow(next_link, callback=self.parse, errback=self.handle_error)

    def parse_item(self, response, quote_data):
        yield CollectedItem(
            kind="quote", **quote_data,
            author_url=response.url,
            birth_date=response.css(".author-born-date::text").get(),
            birth_place=response.css(".author-born-location::text").get(),
            biography=response.css(".author-description::text").get(),
        )

    def handle_error(self, failure):
        self.crawler.stats.inc_value("request_errors")
        self.logger.error("Request failed: %s: %s", failure.request.url, failure.value)

    def closed(self, reason):
        path = Path("data") / f"stats_{self.run_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        stats = dict(self.crawler.stats.get_stats())
        ended = datetime.now(timezone.utc)
        started = stats.get("start_time")
        stats["elapsed_time_seconds"] = (ended - started).total_seconds() if started else 0
        stats["finish_time"] = ended
        stats["finish_reason"] = reason
        path.write_text(json.dumps(stats, ensure_ascii=False, indent=2, default=str) + "\n",
                        encoding="utf-8")
