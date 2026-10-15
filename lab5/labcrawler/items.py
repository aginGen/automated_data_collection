import scrapy


class CollectedItem(scrapy.Item):
    kind = scrapy.Field()
    key = scrapy.Field()
    quote = scrapy.Field()
    author = scrapy.Field()
    tags = scrapy.Field()
    author_url = scrapy.Field()
    birth_date = scrapy.Field()
    birth_place = scrapy.Field()
    biography = scrapy.Field()
    upc = scrapy.Field()
    title = scrapy.Field()
    price = scrapy.Field()
    stock = scrapy.Field()
    reviews = scrapy.Field()
    category = scrapy.Field()
    description = scrapy.Field()
    rating = scrapy.Field()
    url = scrapy.Field()
