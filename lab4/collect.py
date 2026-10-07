from __future__ import annotations

import argparse
import csv
import random
import threading
from email.utils import parsedate_to_datetime
from typing import Callable

import psutil
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlsplit

import pandas as pd
import requests
from parsel import Selector
from playwright.sync_api import Error, TimeoutError, sync_playwright


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or (list(rows[0]) if rows else [])
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


class APIError(RuntimeError):
    pass


class APIClient:
    LOG_FIELDS = ["page", "url", "params", "status", "records", "duration_s",
                  "timestamp", "attempt", "response_bytes", "retry_delay_s", "error"]

    def __init__(self, timeout: float = 20, interval: float = 0.5, retries: int = 2):
        if timeout <= 0 or interval < 0 or retries < 0:
            raise ValueError("Неверные параметры HTTP-клиента")
        self.timeout = timeout
        self.interval = interval
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "university-data-collection-labs/1.0",
            "Accept": "application/json",
        })
        self.logs: list[dict] = []
        self.rate_headers: dict = {}
        self._last_request = 0.0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.session.close()

    @staticmethod
    def retry_delay(value: str | None, attempt: int) -> float:
        backoff = 0.5 * 2 ** attempt + random.uniform(0, 0.25)
        if not value:
            return backoff
        try:
            header_delay = float(value)
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                header_delay = (parsed - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                header_delay = 0
        return max(backoff, header_delay, 0)

    def get_json(self, url: str, params: dict | None = None, page: int = 0,
                 count: Callable | None = None):
        for attempt in range(self.retries + 1):
            pause = self.interval - (time.monotonic() - self._last_request)
            if pause > 0:
                time.sleep(pause)
            self._last_request = time.monotonic()
            started = time.perf_counter()
            entry = dict.fromkeys(self.LOG_FIELDS, "")
            entry.update(page=page, url=url, params=json.dumps(params or {}, ensure_ascii=False),
                         records=0, timestamp=datetime.now(timezone.utc).isoformat(),
                         attempt=attempt + 1, retry_delay_s=0, response_bytes=0)
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as error:
                entry.update(duration_s=round(time.perf_counter() - started, 6), error=str(error))
                self.logs.append(entry)
                raise APIError(f"Сетевая ошибка {url}: {error}") from error
            with response:
                body = response.content
                entry.update(url=response.url, status=response.status_code,
                             response_bytes=len(body),
                             duration_s=round(time.perf_counter() - started, 6))
                self.rate_headers.update({
                    key: value for key, value in response.headers.items()
                    if "ratelimit" in key.lower() or key.lower() == "retry-after"
                })
                temporary_error = response.status_code == 429 or 500 <= response.status_code <= 599
                snippet = body[:200].decode("utf-8", errors="replace")
                if not 200 <= response.status_code <= 299:
                    entry["error"] = f"HTTP {response.status_code}: {snippet}"
                    if temporary_error and attempt < self.retries:
                        delay = self.retry_delay(response.headers.get("Retry-After"), attempt)
                        entry["retry_delay_s"] = round(delay, 6)
                        self.logs.append(entry)
                        time.sleep(delay)
                        continue
                    self.logs.append(entry)
                    raise APIError(f"{url}: {entry['error']}")
                media_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if media_type != "application/json" and not media_type.endswith("+json"):
                    entry["error"] = f"Ожидался JSON, получен {media_type}: {snippet}"
                    self.logs.append(entry)
                    raise APIError(f"{url}: {entry['error']}")
                try:
                    payload = response.json()
                    entry["records"] = count(payload) if count else (len(payload) if isinstance(payload, list) else 1)
                except (ValueError, KeyError, TypeError) as error:
                    entry["error"] = f"Неверный JSON или структура: {snippet}"
                    self.logs.append(entry)
                    raise APIError(f"{url}: {entry['error']}") from error
                self.logs.append(entry)
                return payload, dict(response.headers)
        raise APIError("Исчерпаны попытки запроса")

    def save_log(self, path: Path) -> None:
        write_csv(path, self.logs, self.LOG_FIELDS)

    def metrics(self) -> dict:
        return {
            "requests": len(self.logs),
            "response_bytes": sum(int(row["response_bytes"]) for row in self.logs),
            "retries": sum(int(row["attempt"]) > 1 for row in self.logs),
            "status_counts": {
                str(code): sum(row["status"] == code for row in self.logs)
                for code in sorted({row["status"] for row in self.logs}, key=str)
            },
            "rate_headers": self.rate_headers,
        }


class MemorySampler:
    def __init__(self, pid: int | None = None):
        self.process = psutil.Process(pid)
        self.peak_bytes = 0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _sample(self):
        processes = [self.process]
        try:
            processes += self.process.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return
        rss = 0
        for process in processes:
            try:
                rss += process.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        self.peak_bytes = max(self.peak_bytes, rss)

    def _run(self):
        while not self.stop.wait(0.05):
            self._sample()

    def __enter__(self):
        self._sample()
        self.thread.start()
        return self

    def __exit__(self, *args):
        self._sample()
        self.stop.set()
        self.thread.join(timeout=2)

    @property
    def peak_mib(self):
        return round(self.peak_bytes / 1024 ** 2, 3)


ROOT = Path(__file__).resolve().parent
SOURCES = {
    "scrapingcourse": {
        "url": "https://www.scrapingcourse.com/infinite-scrolling",
        "card": ".product-item", "name": ".product-name", "price": ".product-price",
    },
    "scrapingsandbox": {
        "url": "https://scrapingsandbox.com/infinite-scroll",
        "card": "a.product-card", "name": ".product-name", "price": ".price",
    },
}
REQUIRED = ["key", "title", "price", "url"]
EXTRACT_JS = """(nodes, config) => nodes.slice(0, config.sample_limit || nodes.length).map(node => {
  const text = selector => node.querySelector(selector)?.textContent?.trim() || '';
  const anchor = node.matches('a') ? node : node.querySelector('a');
  return {title: text(config.name), price: text(config.price), url: anchor?.href || '',
          sku: text('.sku'), category: text('.category'),
          image_url: node.querySelector('img')?.src || ''};
})"""


def normalize(rows: list[dict], source: str) -> list[dict]:
    unique = {}
    for raw in rows:
        title = " ".join(raw["title"].split())
        match = re.search(r"[-+]?\d+(?:\.\d+)?", str(raw["price"]).replace(",", ""))
        if not title or not match or not raw["url"]:
            raise ValueError(f"Пустое обязательное поле: {raw}")
        sku = raw.get("sku") or urlsplit(raw["url"]).path.rstrip("/").rsplit("/", 1)[-1]
        row = {"key": source + ":" + sku, "source": source, "sku": sku, "title": title,
               "price": float(match.group()), "currency": "USD", "url": raw["url"],
               "category": " ".join(raw.get("category", "").split()),
               "image_url": raw.get("image_url", "")}
        if row["price"] <= 0:
            raise ValueError(f"Неверная цена: {raw}")
        unique.setdefault(row["key"], row)
    return list(unique.values())


def parse_cards(html: str, source: str) -> list[dict]:
    config = SOURCES[source]
    result = []
    for card in Selector(html).css(config["card"]):
        link = card.attrib.get("href") or card.css("a::attr(href)").get()
        result.append({
            "title": "".join(card.css(config["name"] + " ::text").getall()),
            "price": "".join(card.css(config["price"] + " ::text").getall()),
            "url": urljoin(config["url"], link or ""),
            "sku": card.css(".sku::text").get() or "",
            "category": card.css(".category::text").get() or "",
            "image_url": card.css("img::attr(src)").get() or "",
        })
    return normalize(result, source)


def quality(rows: list[dict], threshold: float = 0.05) -> dict:
    frame = pd.DataFrame(rows)
    missing = frame[REQUIRED].isna() | frame[REQUIRED].astype(str).eq("")
    share = float(missing.any(axis=1).mean()) if len(frame) else 1
    report = {
        "rows": len(frame), "duplicates": int(frame.duplicated("key").sum()),
        "empty_required_share": share, "smoke_ok": share <= threshold,
        "nonpositive_prices": int(frame["price"].le(0).sum()),
        "completeness_percent": {
            name: round(float((column.notna() & column.astype(str).ne("")).mean() * 100), 2)
            for name, column in frame.items()
        },
        "types": {name: str(dtype) for name, dtype in frame.dtypes.items()},
    }
    if not report["smoke_ok"]:
        print(f"WARNING: empty required fields {share:.2%} exceed {threshold:.2%}")
    return report


def save_failure(page, source: str, label: str, error: Exception, directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    prefix = directory / f"{source}_{label}"
    page.screenshot(path=str(prefix.with_suffix(".png")), full_page=False)
    prefix.with_suffix(".html").write_text(page.content(), encoding="utf-8")
    prefix.with_suffix(".txt").write_text(str(error), encoding="utf-8")


def browser_source(source: str, limit: int = 200, block_media: bool = False,
                   max_iterations: int = 35, stagnant_limit: int = 3,
                   artifacts: Path = ROOT / "artifacts", capture: bool = True,
                   benchmark: bool = True) -> tuple[list[dict], list[dict], dict, str]:
    config = SOURCES[source]
    network = {"requests": 0, "response_bytes": 0, "blocked_media": 0, "blocked_robots": 0,
               "metric_errors": [], "xhr": []}
    last_xhr_status = None
    logs = []
    rows = []
    started = time.perf_counter()
    with MemorySampler() as memory, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="university-data-collection-lab4/1.0",
            viewport={"width": 1280, "height": 900}, locale="en-US",
        )
        context.set_default_timeout(config.get("timeout", 20000))
        context.set_default_navigation_timeout(45000)
        page = context.new_page()

        def route_request(route):
            request = route.request
            parsed = urlparse(request.url)
            if parsed.hostname in ("scrapingcourse.com", "www.scrapingcourse.com") and parsed.path.startswith("/ecommerce/"):
                network["blocked_robots"] += 1
                route.abort()
            elif block_media and request.resource_type in ("image", "font", "media"):
                network["blocked_media"] += 1
                route.abort()
            else:
                route.continue_()

        def finished(request):
            response = request.response()
            if response is None or 300 <= response.status < 400:
                return
            try:
                network["response_bytes"] += len(response.body())
            except Error as error:
                network["metric_errors"].append(str(error)[:200])

        def response_seen(response):
            nonlocal last_xhr_status
            network["requests"] += 1
            if response.request.resource_type in ("xhr", "fetch") and urlparse(response.url).hostname in ("www.scrapingcourse.com", "scrapingcourse.com", "scrapingsandbox.com"):
                network["xhr"].append({"url": response.url, "status": response.status})
                if "/ajax/products" in response.url:
                    last_xhr_status = response.status

        page.route("**/*", route_request)
        page.on("requestfinished", finished)
        page.on("response", response_seen)
        failure_count = 0
        try:
            page.goto(config["url"], wait_until="domcontentloaded" if block_media else "load")
            page.locator(config["card"]).first.wait_for(state="visible")
            stagnant = 0
            for iteration in range(max_iterations + 1):
                step_started = time.perf_counter()
                previous = len(rows)
                extracted = page.locator(config["card"]).evaluate_all(EXTRACT_JS, config)
                rows = normalize(extracted, source)[:limit]
                logs.append({
                    "source": source, "iteration": iteration,
                    "elements": len(extracted), "unique_records": len(rows),
                    "growth": len(rows) - previous,
                    "duration_s": round(time.perf_counter() - step_started, 6),
                    "timestamp": datetime.now(timezone.utc).isoformat(), "url": page.url,
                    "status": "ok",
                })
                if len(rows) >= limit or iteration == max_iterations:
                    break
                previous_dom_count = page.locator(config["card"]).count()
                page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
                wait_started = time.perf_counter()
                try:
                    page.wait_for_function(
                        "([selector,count]) => document.querySelectorAll(selector).length > count",
                        arg=[config["card"], previous_dom_count], timeout=8000,
                    )
                    stagnant = 0
                except TimeoutError as error:
                    stagnant += 1
                    logs[-1]["status"] = "source_exhausted" if last_xhr_status == 204 else "no_growth"
                    if last_xhr_status == 204:
                        break
                    failure_count += 1
                    save_failure(page, source, f"iteration_{iteration}", error, artifacts)
                    if stagnant >= stagnant_limit:
                        break
                logs[-1]["duration_s"] += round(time.perf_counter() - wait_started, 6)
                page.wait_for_timeout(250)
            duration = time.perf_counter() - started
            metrics = {
                "source": source, "rows": len(rows), "duration_s": round(duration, 4),
                "iterations": max(0, len(logs) - 1), "failures": failure_count,
                "block_media": block_media, **network,
            }
            if benchmark:
                sample = page.locator(config["card"]).all()[:50]
                tick = time.perf_counter()
                for element in sample:
                    element.locator(config["name"]).text_content()
                    element.locator(config["price"]).text_content()
                per_element = time.perf_counter() - tick
                tick = time.perf_counter()
                page.locator(config["card"]).evaluate_all(EXTRACT_JS, {**config, "sample_limit": len(sample)})
                bulk = time.perf_counter() - tick
                metrics["extraction_benchmark"] = {
                    "sample_elements": len(sample), "per_element_s": round(per_element, 6),
                    "bulk_sample_s": round(bulk, 6),
                    "speedup": round(per_element / max(bulk, 0.000001), 2),
                }
            html = page.content()
            if capture:
                artifacts.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(artifacts / f"{source}_{'optimized' if block_media else 'browser'}.png"),
                                full_page=False)
        except TimeoutError as error:
            save_failure(page, source, "navigation_timeout", error, artifacts)
            raise
        finally:
            context.close()
            browser.close()
    metrics["peak_memory_mib"] = memory.peak_mib
    return rows, logs, metrics, html


def light_course(limit: int = 200, max_pages: int = 30):
    config = SOURCES["scrapingcourse"]
    started = time.perf_counter()
    logs = []
    rows = {}
    bytes_received = 0
    with MemorySampler() as memory, requests.Session() as session:
        session.headers["User-Agent"] = "university-data-collection-lab4/1.0"
        for iteration in range(max_pages + 1):
            url = config["url"] if iteration == 0 else "https://www.scrapingcourse.com/ajax/products"
            params = None if iteration == 0 else {"offset": (iteration - 1) * 10}
            tick = time.perf_counter()
            response = None
            for attempt in range(3):
                response = session.get(url, params=params, timeout=25)
                if (response.status_code == 429 or 500 <= response.status_code < 600) and attempt < 2:
                    time.sleep(APIClient.retry_delay(response.headers.get("Retry-After"), attempt))
                    response.close()
                    continue
                break
            with response:
                response.raise_for_status()
                bytes_received += len(response.content)
                batch = parse_cards(response.text, "scrapingcourse") if response.content else []
                previous = len(rows)
                rows.update({row["key"]: row for row in batch})
                logs.append({
                    "source": "scrapingcourse", "iteration": iteration, "elements": len(batch),
                    "unique_records": len(rows), "growth": len(rows) - previous,
                    "duration_s": round(time.perf_counter() - tick, 6),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "url": response.url, "status": response.status_code,
                })
            if not batch or len(rows) >= limit:
                break
            time.sleep(0.35)
    result = list(rows.values())[:limit]
    return result, logs, {
        "source": "scrapingcourse", "rows": len(result),
        "duration_s": round(time.perf_counter() - started, 4),
        "requests": len(logs), "response_bytes": bytes_received,
        "peak_memory_mib": memory.peak_mib,
    }


def diagnose(output: Path = ROOT):
    output.mkdir(parents=True, exist_ok=True)
    report = {}
    with requests.Session() as session, sync_playwright() as pw:
        session.headers["User-Agent"] = "university-data-collection-lab4/1.0"
        browser = pw.chromium.launch(headless=True)
        try:
            for source, config in SOURCES.items():
                response = session.get(config["url"], timeout=25)
                response.raise_for_status()
                cards = parse_cards(response.text, source)
                (output / f"static_{source}.html").write_text(response.text, encoding="utf-8")
                context = browser.new_context(java_script_enabled=False, viewport={"width": 1280, "height": 900})
                try:
                    page = context.new_page()
                    page.route("**/*", lambda route: route.abort() if route.request.resource_type in ("image", "font", "media") else route.continue_())
                    page.goto(config["url"], wait_until="domcontentloaded", timeout=45000)
                    count = page.locator(config["card"]).count()
                    page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
                    after = page.locator(config["card"]).count()
                    page.screenshot(path=str(output / f"no_js_{source}.png"), full_page=False)
                    report[source] = {
                        "url": config["url"], "http_status": response.status_code,
                        "html_bytes": len(response.content), "static_records": len(cards),
                        "target_text_found": cards[0]["title"] in response.text if cards else False,
                        "no_js_before_scroll": count, "no_js_after_scroll": after,
                        "embedded_complete_json": False,
                    }
                finally:
                    context.close()
        finally:
            browser.close()
    write_json(output / "diagnostics.json", report)
    return report


def run(mode: str = "all"):
    ROOT.joinpath("artifacts").mkdir(exist_ok=True)
    if mode == "diagnose":
        print(json.dumps(diagnose(ROOT / "artifacts"), indent=2))
        return
    baseline_rows, baseline_logs, baseline_metrics = [], [], []
    light_rows, light_logs, light_metrics = [], [], []
    if mode in ("all", "browser"):
        for source in SOURCES:
            rows, logs, metrics, _ = browser_source(source)
            baseline_rows += rows
            baseline_logs += logs
            baseline_metrics.append(metrics)
        write_csv(ROOT / "data_browser.csv", baseline_rows)
        write_csv(ROOT / "collection_log.csv", baseline_logs)
        write_json(ROOT / "metrics_browser.json", baseline_metrics)
        write_json(ROOT / "quality_browser.json", quality(baseline_rows))
        if len(baseline_rows) < 200:
            raise RuntimeError("Собрано меньше 200 уникальных товаров")
    if mode in ("all", "light"):
        rows, logs, metrics = light_course()
        light_rows += rows
        light_logs += logs
        light_metrics.append(metrics)
        rows, logs, metrics, _ = browser_source("scrapingsandbox", block_media=True)
        light_rows += rows
        light_logs += logs
        light_metrics.append(metrics)
        write_csv(ROOT / "data_light.csv", light_rows)
        write_csv(ROOT / "collection_log_light.csv", light_logs)
        write_json(ROOT / "metrics_light.json", light_metrics)
        write_json(ROOT / "quality_light.json", quality(light_rows))
    if (ROOT / "data_browser.csv").exists() and (ROOT / "data_light.csv").exists():
        browser = pd.read_csv(ROOT / "data_browser.csv").fillna("")
        light = pd.read_csv(ROOT / "data_light.csv").fillna("")
        compared = browser.merge(light, on="key", how="outer", suffixes=("_browser", "_light"), indicator=True)
        mismatches = compared.loc[
            compared["_merge"].ne("both") |
            compared["title_browser"].ne(compared["title_light"]) |
            compared["price_browser"].ne(compared["price_light"]) |
            compared["url_browser"].ne(compared["url_light"])
        ]
        write_json(ROOT / "comparison.json", {
            "browser_rows": len(browser), "light_rows": len(light),
            "mismatches": len(mismatches), "fields": ["key", "title", "price", "url"],
        })
        if len(mismatches):
            mismatches.to_csv(ROOT / "mismatches.csv", index=False, encoding="utf-8-sig")
            raise RuntimeError("Браузерный и облегчённый наборы не совпадают")
        (ROOT / "mismatches.csv").unlink(missing_ok=True)
    print("Lab4 completed:", mode, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Вариант 3: бесконечная прокрутка ScrapingCourse и дополнительный ScrapingSandbox.')
    parser.add_argument("--mode", choices=["all", "diagnose", "browser", "light"], default="all")
    run(parser.parse_args().mode)
