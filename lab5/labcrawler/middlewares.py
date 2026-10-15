class NetworkMetricsMiddleware:
    @classmethod
    def from_crawler(cls, crawler):
        instance = cls()
        instance.stats = crawler.stats
        return instance

    def process_response(self, request, response):
        if "cached" not in response.flags:
            self.stats.inc_value("network/request_count")
            self.stats.inc_value("network/response_body_bytes", len(response.body))
        return response
