"""Discover tags recursively from quote cards; emit quote–tag associations."""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, unquote
import re
import scrapy
from quotes_crawler.items import QuoteItem

class TagsSpider(scrapy.Spider):
    name="tags"
    allowed_domains=["quotes.toscrape.com"]
    start_urls=["https://quotes.toscrape.com/"]
    custom_settings={"CLOSESPIDER_ITEMCOUNT":10000, "ITEM_PIPELINES":{
        "quotes_crawler.pipelines.ValidationPipeline":100,
        "quotes_crawler.tag_pipelines.ValidateRelation":150,
        "quotes_crawler.pipelines.CleanPipeline":200,
        "quotes_crawler.tag_pipelines.DeduplicateRelation":300,
        "quotes_crawler.tag_pipelines.StoreRelations":400}}
    def __init__(self,run_id="tags",*args,**kwargs): super().__init__(*args,**kwargs); self.state={}; self.run_id=run_id
    async def start(self):
        for url in self.start_urls: yield scrapy.Request(url,callback=self.parse,errback=self.request_error)
    def parse(self,response):
        for href in response.css("span.tag-item a.tag::attr(href)").getall():
            tag = self.tag_from_url(href)
            if tag is not None: yield response.follow(href,callback=self.parse_tag,errback=self.request_error,cb_kwargs={"source_tag":tag,"page":1})
    def tag_from_url(self, url):
        try:
            if not isinstance(url, str) or not url.strip(): raise ValueError("empty URL")
            parsed = urlparse(url.strip())
            if parsed.scheme and parsed.scheme not in ("http", "https"): raise ValueError("invalid scheme")
            if parsed.scheme and not parsed.netloc: raise ValueError("missing host")
            if parsed.netloc and (parsed.hostname or "").lower() != "quotes.toscrape.com": raise ValueError("foreign host")
            if not parsed.path.startswith("/"): raise ValueError("relative path")
            match = re.fullmatch(r"/tag/([^/]+)/(?:page/[1-9][0-9]*/)?", parsed.path)
            if not match: raise ValueError("invalid tag path")
            tag = unquote(match.group(1)).strip().lower()
            if not tag or "/" in tag or any(ch.isspace() for ch in tag): raise ValueError("invalid tag")
            return tag
        except (ValueError, TypeError):
            self.crawler.stats.inc_value("tag/invalid_url")
            return None
    def parse_tag(self,response,source_tag,page):
        self.crawler.stats.inc_value("tag/pages")
        self.state.setdefault("authors",{}); self.state.setdefault("pending",{})
        for card in response.css("div.quote"):
            tags=card.css("div.tags a.tag::text").getall()
            for href in card.css("div.tags a.tag::attr(href)").getall():
                tag = self.tag_from_url(href)
                if tag is not None: yield response.follow(href,callback=self.parse_tag,errback=self.request_error,cb_kwargs={"source_tag":tag,"page":1})
            context=dict(quote=card.css("span.text::text").get(),author=card.css("small.author::text").get(),tags=tags,source_url=response.url,list_page=page,source_tag=source_tag,collected_at=datetime.now(timezone.utc).isoformat())
            link=card.css("span a[href*='/author/']::attr(href)").get()
            if not link:
                self.crawler.stats.inc_value("dropped/missing_fields"); continue
            url=response.urljoin(link).rstrip("/")+"/"; context["author_url"]=url
            if url in self.state["authors"]: yield QuoteItem(**context,**self.state["authors"][url])
            elif url in self.state["pending"]: self.state["pending"][url].append(context)
            else:
                self.state["pending"][url]=[]
                yield response.follow(url,callback=self.parse_item,errback=self.request_error,cb_kwargs={"author_url":url,"first_context":context})
        next_url=response.css("li.next a::attr(href)").get()
        if next_url: yield response.follow(next_url,callback=self.parse_tag,errback=self.request_error,cb_kwargs={"source_tag":source_tag,"page":page+1})
    def parse_item(self,response,author_url,first_context):
        details=dict(born_date=response.css("span.author-born-date::text").get(),born_location=response.css("span.author-born-location::text").get(),biography=" ".join(response.css("div.author-description ::text").getall()))
        self.crawler.stats.inc_value("author/pages"); self.state["authors"][author_url]=details
        for context in [first_context]+self.state["pending"].pop(author_url,[]): yield QuoteItem(**context,**details)
    def request_error(self,failure):
        self.crawler.stats.inc_value("errors/request"); self.logger.error("Request failed: %s",failure)
        url=failure.request.cb_kwargs.get("author_url")
        if url: self.crawler.stats.inc_value("errors/affected_relations",1+len(self.state.get("pending",{}).pop(url,[])))
    def closed(self,reason):
        stats=dict(self.crawler.stats.get_stats()); stats["finish_reason"]=reason; stats["finish_time"]=datetime.now(timezone.utc)
        if stats.get("start_time"): stats["duration_seconds"]=(stats["finish_time"]-stats["start_time"]).total_seconds()
        Path("data").mkdir(exist_ok=True); Path("data/stats_"+self.run_id+".json").write_text(json.dumps(stats,ensure_ascii=False,indent=2,default=str),encoding="utf8")
