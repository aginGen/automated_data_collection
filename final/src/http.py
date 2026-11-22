import gzip
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from random import uniform
from time import monotonic, sleep
from urllib.parse import urlsplit, urlunsplit

import requests
from protego import Protego
from urllib3.exceptions import HTTPError as WireError


class SourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict
    body: str
    wire_bytes: int


def status_kind(status, expected):
    if status in expected:
        return "ok", False
    if status == 429:
        return "rate_limit", True
    if status in (401, 403):
        return "access_denied", False
    if status == 404:
        return "not_found", False
    if status in (500, 502, 503, 504):
        return "temporary_server_error", True
    if status is None:
        return "network_error", True
    return "unexpected_status", False


def retry_after(value):
    if value is None:
        return None
    try:
        return max(0.0, float(int(value)))
    except ValueError:
        try:
            target = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        return max(0.0, (target - datetime.now(timezone.utc)).total_seconds())


class RateLimiter:
    def __init__(self, rate, jitter):
        self.interval = 1 / rate
        self.jitter = jitter
        self.last_request = 0.0
        self.spread = 0.0

    def acquire(self, robots_interval):
        base = max(self.interval, robots_interval)
        if self.last_request:
            sleep(max(0.0, self.last_request + base * (1 + self.spread) - monotonic()))
        self.last_request = monotonic()
        self.spread = uniform(0, self.jitter)


class CircuitBreaker:
    def __init__(self, host, log, failures, cooldown):
        self.host = host
        self.log = log
        self.threshold = failures
        self.cooldown = cooldown
        self.failures = 0
        self.state = "closed"
        self.opened = 0.0
        self.denied = False

    def allow(self):
        if self.denied:
            return False
        if self.state == "open":
            if monotonic() - self.opened < self.cooldown:
                return False
            self.state = "half_open"
            self.log.log("circuit_half_open", host=self.host)
        return True

    def success(self):
        if self.state == "half_open":
            self.log.log("circuit_closed", host=self.host)
        self.failures = 0
        self.state = "closed"

    def failure(self, reason, *, hard=False):
        self.failures += 1
        if hard or self.state == "half_open" or self.failures >= self.threshold:
            self.state = "open"
            self.opened = monotonic()
            self.denied = hard
            self.log.log("circuit_open", host=self.host, reason=reason, failures=self.failures)


class HttpClient:
    def __init__(self, settings, sources, contact, logger):
        self.settings = settings
        self.sources = sources
        self.log = logger
        self.agent_token = "pgnu-course-price-study"
        self.user_agent = f"{self.agent_token}/1.0 (+{contact})"
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent, "Accept-Encoding": "gzip"})
        self.robots = {}
        self.limiters = {}
        self.breakers = {}
        for options in sources.values():
            host = urlsplit(options["url"]).netloc
            limit = options["requests_per_second"]
            if host in self.limiters:
                limit = min(limit, 1 / self.limiters[host].interval)
            self.limiters[host] = RateLimiter(limit, settings["jitter"])
            self.breakers[host] = CircuitBreaker(
                host, logger, settings["breaker_failures"], settings["breaker_cooldown"]
            )

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.session.close()

    def check_robots(self, source):
        entry = urlsplit(self.sources[source]["url"])
        key = entry.netloc
        if key in self.robots:
            return self.robots[key][2]
        robots_url = urlunsplit((entry.scheme, entry.netloc, "/robots.txt", "", ""))
        expected = (200, 404) if self.sources[source]["missing_robots_ok"] else (200,)
        response = self.fetch(source, robots_url, expected=expected, robots_request=True)
        parser = Protego.parse(response.body if response.status == 200 else "")
        delay = parser.crawl_delay(self.agent_token)
        rate = parser.request_rate(self.agent_token)
        rate_delay = rate.seconds / rate.requests if rate and rate.requests else 0
        effective = max(self.limiters[key].interval, delay or 0, rate_delay)
        result = {
            "url": robots_url,
            "status": response.status,
            "rules": response.body if response.status == 200 else "",
            "entry_allowed": parser.can_fetch(self.sources[source]["url"], self.agent_token),
            "crawl_delay": delay,
            "request_rate": str(rate) if rate else None,
            "sitemaps": list(parser.sitemaps),
            "minimum_interval_s": effective,
        }
        self.robots[key] = (parser, effective, result)
        self.log.log("robots_checked", source=source, **result)
        return result

    def fetch(self, source, url, *, headers=None, cached_bytes=0, expected=(200, 304), robots_request=False):
        entry = urlsplit(self.sources[source]["url"])
        address = urlsplit(url)
        if (address.scheme, address.netloc) != (entry.scheme, entry.netloc):
            raise SourceError(f"Адрес за пределами источника {source}")
        host = address.netloc
        if not robots_request:
            self.check_robots(source)
            parser, delay, _ = self.robots[host]
            if not parser.can_fetch(url, self.agent_token):
                self.log.log("robots_denied", source=source, url=url)
                raise SourceError(f"URL запрещён robots.txt: {url}")
        else:
            delay = 0

        breaker = self.breakers[host]
        waited = 0.0
        for attempt in range(1, self.settings["max_attempts"] + 1):
            if not breaker.allow():
                self.log.log("circuit_skip", source=source, host=host, url=url)
                raise SourceError(f"Предохранитель открыт для {host}")
            self.limiters[host].acquire(delay)
            started = monotonic()
            status = None
            body = ""
            raw = b""
            decoded = b""
            encoding = ""
            response_headers = {}
            error = None
            try:
                with self.session.get(
                    url, headers=headers, allow_redirects=False, stream=True,
                    timeout=(self.settings["connect_timeout"], self.settings["read_timeout"]),
                ) as response:
                    response_headers = response.headers.copy()
                    raw = response.raw.read(decode_content=False)
                    encoding = response_headers.get("Content-Encoding", "").casefold()
                    decoded = gzip.decompress(raw) if encoding == "gzip" and raw else raw
                    body = decoded.decode("utf-8-sig", errors="strict")
                    status = response.status_code
            except (requests.RequestException, WireError, OSError, UnicodeError) as exc:
                error = type(exc).__name__

            kind, retryable = status_kind(status, expected)
            millis = round(1000 * (monotonic() - started), 3)
            self.log.log(
                "request", source=source, host=host, url=url, status=status, ms=millis,
                attempt=attempt, accepted=kind == "ok", kind=kind, error=error,
                conditional=bool(headers), wire_bytes=len(raw), decoded_bytes=len(decoded),
                encoding=encoding, saved_304_bytes=cached_bytes if status == 304 else 0,
            )
            if kind == "ok":
                breaker.success()
                return Response(status, response_headers, body, len(raw))

            if kind == "access_denied":
                breaker.failure(kind, hard=True)
                self.log.incident(source, url, kind, status, body[:4000])
            elif retryable:
                breaker.failure(kind)

            if not retryable or attempt == self.settings["max_attempts"] or breaker.state == "open":
                if kind != "access_denied":
                    self.log.incident(source, url, kind, status, body[:4000])
                raise SourceError(f"{source}: {status if status is not None else error or kind} на {url}")

            limit = min(self.settings["backoff_cap"], self.settings["backoff_base"] * 2 ** (attempt - 1))
            required = retry_after(response_headers.get("Retry-After"))
            pause = max(required or 0.0, uniform(0, limit))
            if waited + pause > self.settings["retry_wait_budget"]:
                self.log.incident(source, url, "retry_budget_exhausted", status, body[:4000])
                raise SourceError(f"{source}: время ожидания Retry-After превышает бюджет повтора")
            self.log.log("retry_wait", source=source, url=url, seconds=round(pause, 3), retry_after=required)
            sleep(pause)
            waited += pause
        raise AssertionError("max_attempts должен быть положительным")

    def bad_payload(self, source, url, reason, body):
        self.breakers[urlsplit(url).netloc].failure(reason, hard=True)
        self.log.incident(source, url, reason, 200, body[:12000])
        raise SourceError(f"{source}: {reason} на {url}")


def checked_document(client, store, source, url, parser):
    headers, size = store.conditional(url)
    response = client.fetch(source, url, headers=headers, cached_bytes=size)
    if response.status == 304 and url not in store.latest:
        client.bad_payload(source, url, "304 без локальной копии", "")
    body = store.latest[url]["payload"] if response.status == 304 else response.body
    if response.status == 200:
        lowered = body[:12000].casefold()
        markers = ("verify you are human", "<title>access denied", "unusual traffic", "cf-challenge")
        if len(body) < 100 or any(marker in lowered for marker in markers):
            client.bad_payload(source, url, "ответ похож на заглушку или блокировку", body)
    try:
        result = parser(body, url)
    except (ValueError, KeyError, TypeError) as exc:
        client.bad_payload(source, url, f"неожиданная структура ответа: {exc}", body)
    envelope = store.put(source, url, response)
    return result, envelope, response.status
