import json
from datetime import datetime, timezone
from pathlib import Path

import scrapy

from labcrawler.items import CollectedItem


class BooksSpider(scrapy.Spider):
    name = "books"
    allowed_domains = ["books.toscrape.com"]
    start_urls = ["https://books.toscrape.com/catalogue/page-1.html"]

    def __init__(self, run_id="books", max_pages="20", **kwargs):
        super().__init__(**kwargs)
        self.run_id = run_id
        self.max_pages = int(max_pages)
        self.state = {}

    async def start(self):
        for url in self.start_urls:
            yield scrapy.Request(url, callback=self.parse, errback=self.handle_error,
                                 dont_filter=False)

    def parse(self, response):
        number = int(response.url.rsplit("page-", 1)[-1].split(".")[0])
        self.crawler.stats.inc_value("list_pages")
        for card in response.css("article.product_pod"):
            link = card.css("h3 a::attr(href)").get()
            title = card.css("h3 a::attr(title)").get()
            rating = card.css("p.star-rating::attr(class)").get()
            if not link:
                self.crawler.stats.inc_value("dropped/missing_link")
                continue
            yield response.follow(link, callback=self.parse_item,
                                  cb_kwargs={"list_data": {"title": title, "rating": rating}},
                                  errback=self.handle_error)
        next_link = response.css("li.next a::attr(href)").get()
        if next_link and number < self.max_pages:
            yield response.follow(next_link, callback=self.parse, errback=self.handle_error)

    def parse_item(self, response, list_data):
        table = {
            row.css("th::text").get(): row.css("td::text").get()
            for row in response.css("table.table-striped tr")
        }
        category = response.css("ul.breadcrumb li a::text").getall()
        yield CollectedItem(
            kind="book", **list_data,
            upc=table.get("UPC"), price=table.get("Price (excl. tax)"),
            stock=table.get("Availability"), reviews=table.get("Number of reviews"),
            category=category[-1] if category else None,
            description=response.css("#product_description + p::text").get(),
            url=response.url,
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
