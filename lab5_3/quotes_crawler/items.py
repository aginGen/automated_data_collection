import scrapy

class QuoteItem(scrapy.Item):
    business_key = scrapy.Field()
    quote = scrapy.Field()
    author = scrapy.Field()
    tags = scrapy.Field()
    author_url = scrapy.Field()
    born_date = scrapy.Field()
    born_location = scrapy.Field()
    biography = scrapy.Field()
    source_url = scrapy.Field()
    list_page = scrapy.Field()
    collected_at = scrapy.Field()
    source_tag = scrapy.Field()
