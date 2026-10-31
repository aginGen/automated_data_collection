"""ЛР4, вариант 3. Реальная прокрутка и прямой HTML-XHR; без обхода защиты."""
from __future__ import annotations

import argparse
import os
import csv
import json
import random
import sys
import threading
import time
import warnings
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import pandas as pd
import psutil
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

ROOT = Path(__file__).resolve().parent.parent / "outputs" / "lab4" / "rendering"
BASE = "https://www.scrapingcourse.com"
URL = BASE + "/infinite-scrolling"
API = BASE + "/ajax/products"
UA = "UniversityLab4/1.0 (educational training-site collection)"
ITEM = "[data-testid='product-grid'] .product-item"
FIELDS = ["snapshot_id", "product_id", "name", "price", "currency", "url", "observed_at"]
KEY = ["snapshot_id", "product_id"]
LOG_FIELDS = ["method", "snapshot_id", "iteration", "elements", "new_records", "total", "duration_sec", "timestamp", "url", "status", "error"]
EXTRACT = """els => els.map(el => ({
  name: el.querySelector('.product-name')?.textContent.trim() ?? '',
  price: el.querySelector('.product-price')?.textContent.trim() ?? '',
  url: el.querySelector('a[href]')?.href ?? ''
}))"""


def utc():
    return datetime.now(timezone.utc).isoformat()


def save_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path, rows, fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class MemoryMeter:
    """Пик суммы RSS корня и дочерних процессов, опрос каждые 50 мс."""
    def __init__(self, extra_pids=()):
        self.peak = 0
        self.stop = threading.Event()
        self.process = psutil.Process()
        self.extra_pids = list(extra_pids)

    def sample(self):
        while not self.stop.is_set():
            total = 0
            processes = {p.pid: p for p in [self.process] + self.process.children(recursive=True)}
            for pid in self.extra_pids:
                try:
                    p = psutil.Process(pid)
                    processes.update({q.pid: q for q in [p] + p.children(recursive=True)})
                except psutil.NoSuchProcess:
                    continue
            for p in processes.values():
                try:
                    total += p.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            self.peak = max(self.peak, total)
            self.stop.wait(0.05)

    def __enter__(self):
        self.thread = threading.Thread(target=self.sample, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()


class HttpClient:
    def __init__(self, pause=1.0):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept": "text/html,*/*;q=0.8"})
        self.pause = pause
        self.last = 0.0
        self.network = []

    def get(self, url, params=None):
        for attempt in range(3):
            # Только ограничение нагрузки, не ожидание появления данных.
            time.sleep(max(0, self.pause - (time.perf_counter() - self.last)))
            self.last = time.perf_counter()
            r = self.session.get(url, params=params, timeout=(10, 30), stream=True, allow_redirects=False)
            r.raw.decode_content = False
            wire = r.raw.read()
            import gzip, zlib
            encoding = r.headers.get("Content-Encoding", "").lower()
            if encoding == "gzip":
                body = gzip.decompress(wire)
            elif encoding == "deflate":
                body = zlib.decompress(wire)
            elif encoding == "br":
                import brotli
                body = brotli.decompress(wire)
            else:
                body = wire
            r._content, r._content_consumed = body, True
            r.encoding = "utf-8"
            self.network.append({"url": r.url, "method": "GET", "status": r.status_code,
                                 "body_bytes": len(wire), "resource_type": "http", "attempt": attempt + 1})
            r.close()
            if r.status_code == 429 or 500 <= r.status_code < 600:
                if attempt == 2:
                    r.raise_for_status()
                retry = r.headers.get("Retry-After", "0")
                try:
                    delay = float(retry)
                except ValueError:
                    from email.utils import parsedate_to_datetime
                    delay = max(0, (parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds())
                time.sleep(max(delay, 2 ** attempt + random.random()))
                continue
            r.raise_for_status()
            return r
        raise RuntimeError("Исчерпаны попытки HTTP-запроса")

    def close(self):
        self.session.close()


def html_items(html):
    soup = BeautifulSoup(html, "html.parser")
    return [{"name": el.select_one(".product-name").get_text(strip=True) if el.select_one(".product-name") else "",
             "price": el.select_one(".product-price").get_text(strip=True) if el.select_one(".product-price") else "",
             "url": el.select_one("a[href]")["href"] if el.select_one("a[href]") else ""}
            for el in soup.select(".product-item")]


def normalize(item, snapshot):
    url = item["url"].strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.hostname not in {"scrapingcourse.com", "www.scrapingcourse.com"} or not parsed.path.startswith("/ecommerce/product/"):
        raise ValueError(f"Некорректный адрес товара: {url!r}")
    price = str(Decimal(item["price"].replace("$", "").replace(",", "").strip()).quantize(Decimal("0.01")))
    if not item["name"].strip() or Decimal(price) <= 0:
        raise ValueError("Пустое название или неположительная цена")
    # urlparse.path отделяет параметры после ';', встречающиеся в учебных slug
    # с &trade;. Ключ берём из полного URL, чтобы не потерять часть slug.
    product_id = url.rsplit("/", 1)[-1]
    name = " ".join(item["name"].split())
    return dict(zip(FIELDS, [snapshot, product_id, name, price, "USD", url, utc()]))


def merge_items(target, items, snapshot, errors):
    added = 0
    for item in items:
        try:
            record = normalize(item, snapshot)
        except (ValueError, InvalidOperation) as e:
            errors.append({"snapshot_id": snapshot, "item": item, "error": str(e)})
            continue
        if record["product_id"] not in target:
            target[record["product_id"]] = record
            added += 1
    return added


def record_log(log, method, snapshot, iteration, elements, added, total, start, url, status="ok", error=""):
    log.append(dict(zip(LOG_FIELDS, [method, snapshot, iteration, elements, added, total,
                                    round(time.perf_counter() - start, 6), utc(), url, status, error])))


def robots_check(out):
    client = HttpClient()
    rules = {}
    redirects = []
    try:
        for host in ["www.scrapingcourse.com", "scrapingcourse.com"]:
            r = client.get("https://" + host + "/robots.txt")
            if r.status_code in {301, 302, 307, 308}:
                location = r.headers.get("Location", "")
                redirect = urlparse(location)
                if not (redirect.scheme == "https" and redirect.hostname == "www.scrapingcourse.com"
                        and redirect.port in {None, 443} and redirect.path == "/robots.txt"
                        and not redirect.query and not redirect.username):
                    raise RuntimeError(f"Неожиданный robots.txt redirect: {location}")
                redirects.append({"requested_url": r.url, "effective_url": location})
                r = client.get(BASE + "/robots.txt")
            rp = RobotFileParser()
            rp.parse(r.text.splitlines())
            rules[host] = rp
            (out / f"robots_{host}.txt").write_text(r.text, encoding="utf-8")
        save_json(out / "robots_redirects.json", redirects)
        for url in [URL, API, BASE + "/ecommerce"]:
            if not rules[urlparse(url).hostname].can_fetch(UA, url):
                raise RuntimeError(f"robots.txt запрещает {url}")
    finally:
        client.close()
    return rules


def path_allowed(rules, url):
    p = urlparse(url)
    # urllib.robotparser не реализует wildcard в Disallow. Учитываем фактическое
    # правило площадки /ecommerce/* явно, включая картинки wp-content.
    if p.hostname in rules and p.path.startswith("/ecommerce/"):
        return False
    return p.hostname not in rules or rules[p.hostname].can_fetch(UA, url)


def save_failure(page, out, stem, message):
    out.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out / f"{stem}.png"), full_page=False, timeout=10000)
    (out / f"{stem}.html").write_text(page.content(), encoding="utf-8")
    (out / f"{stem}.txt").write_text(message, encoding="utf-8")


def browser_proxy():
    """Respect an explicitly configured proxy; never assume a local proxy."""
    from urllib.parse import urlsplit, unquote
    value = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    if not value:
        return {}
    parsed = urlsplit(value if "://" in value else "http://" + value)
    if not parsed.hostname:
        raise ValueError("Invalid proxy URL")
    proxy = {"server": f"{parsed.scheme}://{parsed.hostname}" + (f":{parsed.port}" if parsed.port else "")}
    if parsed.username: proxy["username"] = unquote(parsed.username)
    if parsed.password: proxy["password"] = unquote(parsed.password)
    return {"proxy": proxy}


def make_context(browser, js=True):
    ctx = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 800},
                              locale="en-US", java_script_enabled=js, service_workers="block")
    ctx.set_default_timeout(12000)
    ctx.set_default_navigation_timeout(35000)
    return ctx


def route_page(page, block, rules, stats):
    def route_handler(route):
        request = route.request
        p = urlparse(request.url)
        # Запрещённые robots.txt пути не посещаем даже как картинки.
        denied = not path_allowed(rules, request.url)
        if denied or (block and request.resource_type in {"image", "font", "media"}):
            stats["blocked"] += 1
            route.abort()
        else:
            route.continue_()
    page.route("**/*", route_handler)


def collect_page(page, snapshot, limit, rounds, pause, log, errors, out):
    target, stalls = {}, 0
    start = time.perf_counter()
    page.goto(URL, wait_until="load")
    page.wait_for_selector(ITEM)
    added = merge_items(target, page.eval_on_selector_all(ITEM, EXTRACT), snapshot, errors)
    record_log(log, "browser", snapshot, 0, page.locator(ITEM).count(), added, len(target), start, page.url)
    for iteration in range(1, rounds + 1):
        if len(target) >= limit:
            return list(target.values())[:limit], "record_limit"
        time.sleep(pause)  # Пауза вежливости; данные ниже ожидаются по ответу и DOM.
        start = time.perf_counter()
        previous = page.locator(ITEM).count()
        status, error = "ok", ""
        try:
            page.evaluate("window.scrollTo(0, 0)")
            # Выход sentinel из viewport подтверждается состоянием, не sleep.
            page.wait_for_function("() => document.querySelector('#end-of-page').getBoundingClientRect().top > innerHeight")
            with page.expect_response(lambda r: "/ajax/products?" in r.url, timeout=5000) as caught:
                page.locator("#end-of-page").scroll_into_view_if_needed()
            response = caught.value
            if response.status not in (200, 204):
                raise RuntimeError(f"XHR {response.status}: {response.url}")
            if response.status == 200:
                page.wait_for_function("([sel,n]) => document.querySelectorAll(sel).length > n", arg=[ITEM, previous], timeout=5000)
            else:
                status = "exhausted_204"
        except PWTimeout as exc:
            status, error = "timeout", str(exc).splitlines()[0]
            save_failure(page, out, f"timeout_s{snapshot}_i{iteration}", str(exc))
        items = page.eval_on_selector_all(ITEM, EXTRACT)
        added = merge_items(target, items, snapshot, errors)
        record_log(log, "browser", snapshot, iteration, len(items), added, len(target), start, page.url, status, error)
        print(f"browser s{snapshot} i{iteration}: DOM={len(items)}, +{added}, unique={len(target)}", flush=True)
        stalls = stalls + 1 if added == 0 else 0
        if stalls >= 2:
            return list(target.values())[:limit], "no_growth_2"
    return list(target.values())[:limit], "iteration_limit"


def browser_run(out, snapshots=1, block=False, limit=200, rounds=24, pause=1.0, benchmark=False):
    out = Path(out)
    artifacts = out / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    rules = robots_check(artifacts)
    rows, logs, errors, network = [], [], [], []
    stats = {"blocked": 0}
    reasons = []
    start = time.perf_counter()
    with MemoryMeter() as memory, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, **browser_proxy())
        context = make_context(browser)
        try:
            page = context.new_page()
            route_page(page, block, rules, stats)

            def finished(req):
                try:
                    response = req.response()
                    size = req.sizes()["responseBodySize"]
                    network.append({"url": req.url, "method": req.method, "status": response.status if response else 0,
                                    "body_bytes": size, "resource_type": req.resource_type, "attempt": 1})
                except Exception as exc:
                    errors.append({"network_url": req.url, "error": str(exc)})

            page.on("requestfinished", finished)
            for snapshot in range(1, snapshots + 1):
                result, reason = collect_page(page, snapshot, limit, rounds, pause, logs, errors, artifacts)
                rows.extend(result)
                reasons.append(reason)
                page.screenshot(path=str(artifacts / f"collected_s{snapshot}.png"), full_page=False)
            elapsed = time.perf_counter() - start
            collection_peak = memory.peak
            if benchmark:
                # Одинаковое извлечение трёх полей; три парных повтора на одном DOM.
                measurements = []
                for repeat in range(3):
                    t = time.perf_counter()
                    bulk = page.eval_on_selector_all(ITEM, EXTRACT)
                    bulk_sec = time.perf_counter() - t
                    t = time.perf_counter()
                    elementwise = []
                    for item in page.locator(ITEM).all():
                        elementwise.append({"name": item.locator(".product-name").text_content().strip(),
                                            "price": item.locator(".product-price").text_content().strip(),
                                            "url": item.get_by_role("link").get_attribute("href")})
                    per_sec = time.perf_counter() - t
                    if bulk != elementwise:
                        raise RuntimeError("Не совпали способы извлечения")
                    measurements.append({"repeat": repeat + 1, "elements": len(bulk), "bulk_sec": bulk_sec, "elementwise_sec": per_sec})
                save_json(artifacts / "extraction_benchmark.json", measurements)
        except Exception as exc:
            if "page" in locals() and not page.is_closed():
                save_failure(page, artifacts, "fatal_browser", str(exc))
            raise
        finally:
            write_csv(out / "collection_log.csv", logs, LOG_FIELDS)
            save_json(artifacts / "item_errors.json", errors)
            context.close()
            browser.close()
    write_csv(out / "data_browser.csv", rows, FIELDS)
    write_csv(artifacts / "network_browser.csv", network, ["url", "method", "status", "body_bytes", "resource_type", "attempt"])
    metrics = {"method": "Playwright blocked" if block else "Playwright baseline", "rows": len(rows),
               "unique_products": len({r["product_id"] for r in rows}), "seconds": elapsed,
               "requests": len(network), "body_bytes": sum(r["body_bytes"] for r in network),
               "peak_rss_mb": collection_peak / 1_000_000, "seconds_per_record": elapsed / max(1, len(rows)),
               "blocked_requests": stats["blocked"], "stop_reasons": reasons, "measured_at": utc()}
    save_json(artifacts / "metrics_browser.json", metrics)
    return metrics


def light_run(out, snapshots=1, limit=200, rounds=24, pause=1.0):
    out = Path(out)
    (out / "artifacts").mkdir(parents=True, exist_ok=True)
    robots_check(out / "artifacts")
    client = HttpClient(pause)
    rows, log, errors, reasons = [], [], [], []
    start = time.perf_counter()
    with MemoryMeter() as memory:
        try:
            for snapshot in range(1, snapshots + 1):
                target, stalls = {}, 0
                for iteration in range(rounds + 1):
                    t = time.perf_counter()
                    offset = max(0, (iteration - 1) * 10)
                    r = client.get(URL if iteration == 0 else API, params=None if iteration == 0 else {"offset": offset})
                    if r.status_code != 204 and "html" not in r.headers.get("Content-Type", "").lower():
                        raise ValueError("Ожидался HTML-фрагмент, а не JSON")
                    items = html_items(r.text)
                    added = merge_items(target, items, snapshot, errors)
                    record_log(log, "http", snapshot, iteration, len(items), added, len(target), t, r.url, str(r.status_code))
                    stalls = stalls + 1 if added == 0 else 0
                    if len(target) >= limit or stalls >= 2:
                        reasons.append("record_limit" if len(target) >= limit else "no_growth_2")
                        break
                else:
                    reasons.append("iteration_limit")
                rows.extend(list(target.values())[:limit])
        finally:
            client.close()
            write_csv(out / "collection_log_light.csv", log, LOG_FIELDS)
            save_json(out / "artifacts" / "item_errors_light.json", errors)
    elapsed = time.perf_counter() - start
    write_csv(out / "data_light.csv", rows, FIELDS)
    write_csv(out / "artifacts" / "network_light.csv", client.network, ["url", "method", "status", "body_bytes", "resource_type", "attempt"])
    metrics = {"method": "HTTP HTML-XHR", "rows": len(rows), "unique_products": len({r["product_id"] for r in rows}),
               "seconds": elapsed, "requests": len(client.network), "body_bytes": sum(r["body_bytes"] for r in client.network),
               "peak_rss_mb": memory.peak / 1_000_000, "seconds_per_record": elapsed / max(1, len(rows)),
               "stop_reasons": reasons, "measured_at": utc()}
    save_json(out / "artifacts" / "metrics_light.json", metrics)
    return metrics


def diagnose(out):
    out = Path(out) / "artifacts"
    out.mkdir(parents=True, exist_ok=True)
    rules = robots_check(out)
    client = HttpClient()
    try:
        raw = client.get(URL)
        (out / "source_requests.html").write_text(raw.text, encoding="utf-8")
        control = client.get(BASE + "/ecommerce")
        # Корневой адрес перенаправляет на /ecommerce/, запрещённый текущим robots.txt.
        # Фиксируем редирект, но не переходим к запрещённому разделу.
        (out / "control_redirect.txt").write_text(str(control.status_code) + " " + control.headers.get("Location", ""), encoding="utf-8")
    finally:
        client.close()
    xhr = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, **browser_proxy())
        try:
            nojs = make_context(browser, js=False)
            try:
                p = nojs.new_page()
                route_page(p, True, rules, {"blocked": 0})
                p.goto(URL, wait_until="load")
                nojs_count = p.locator(ITEM).count()
                p.screenshot(path=str(out / "diagnosis_nojs.png"))
                (out / "diagnosis_nojs.html").write_text(p.content(), encoding="utf-8")
            finally:
                nojs.close()
            ctx = make_context(browser)
            try:
                p = ctx.new_page()
                route_page(p, True, rules, {"blocked": 0})
                p.on("response", lambda r: xhr.append({"url": r.url, "method": r.request.method,
                     "resource_type": r.request.resource_type, "status": r.status,
                     "content_type": r.headers.get("content-type", "")}) if "/ajax/products" in r.url else None)
                p.goto(URL, wait_until="load")
                before = p.locator(ITEM).count()
                with p.expect_response(lambda r: "/ajax/products?" in r.url) as response:
                    p.locator("#end-of-page").scroll_into_view_if_needed()
                resp = response.value
                p.wait_for_function("n => document.querySelectorAll('.product-item').length > n", arg=before)
                (out / "xhr_sample.html").write_text(resp.text(), encoding="utf-8")
                items = p.eval_on_selector_all(ITEM, EXTRACT)
                # Текст товара, отсутствующего в первых 12 карточках.
                extra = next((i["name"] for i in items if i["name"] not in raw.text), "")
                if not extra:
                    p.evaluate("window.scrollTo(0,0)")
                    time.sleep(1.0)  # Пауза вежливости перед второй прокруткой.
                    with p.expect_response(lambda r: "/ajax/products?" in r.url):
                        p.locator("#end-of-page").scroll_into_view_if_needed()
                    p.wait_for_function("n => document.querySelectorAll('.product-item').length > n", arg=len(items))
                    items = p.eval_on_selector_all(ITEM, EXTRACT)
                    extra = next((i["name"] for i in items if i["name"] not in raw.text), "")
                p.screenshot(path=str(out / "diagnosis_js.png"))
            finally:
                ctx.close()
        finally:
            browser.close()
    data = {"url": URL, "status": raw.status_code, "html_bytes": len(raw.content),
            "static_products": len(html_items(raw.text)), "nojs_products": nojs_count,
            "after_scroll_dom": len(items), "target_text": extra, "target_in_source": extra in raw.text if extra else None,
            "embedded_product_json": False, "control_url": control.url,
            "control_status": control.status_code, "control_location": control.headers.get("Location", ""),
            "control_disallowed_after_redirect": True,
            "xhr": xhr, "timestamp": utc()}
    save_json(out / "diagnosis.json", data)
    return data


def smoke_check(frame, threshold=0.05):
    required = ["snapshot_id", "product_id", "name", "price", "currency", "url", "observed_at"]
    result = {}
    for field in required:
        share = 1.0 if field not in frame or frame.empty else float((frame[field].isna() | frame[field].astype(str).str.strip().eq("")).mean())
        result[field] = share
        if share > threshold:
            warnings.warn(f"smoke-check: {field}: {share:.1%} пустых, порог {threshold:.0%}", stacklevel=2)
    return result


def check(out, persist=True):
    out = Path(out)
    frames = [pd.read_csv(out / n, dtype={"product_id": "string", "name": "string", "url": "string"})
              for n in ["data_browser.csv", "data_light.csv"]]
    quality = []
    for frame in frames:
        frame["snapshot_id"] = frame.snapshot_id.astype("Int64")
        frame["price"] = pd.to_numeric(frame.price, errors="raise")
        frame["observed_at"] = pd.to_datetime(frame.observed_at, utc=True, errors="raise")
        quality.append({"rows": len(frame), "unique_products": frame.product_id.nunique(),
                        "duplicate_observation_keys": int(frame.duplicated(KEY).sum()),
                        "empty_shares": smoke_check(frame), "nonpositive_prices": int(frame.price.le(0).sum()),
                        "snapshots": {str(k): int(v) for k, v in frame.groupby("snapshot_id").size().items()}})
    fields = ["name", "price", "currency", "url"]
    merged = frames[0].merge(frames[1], on=KEY, how="outer", suffixes=("_browser", "_light"), indicator=True, validate="one_to_one")
    diff = merged._merge.ne("both")
    for field in fields:
        diff |= merged[field + "_browser"].ne(merged[field + "_light"])
    mismatches = merged[diff].copy()
    if persist:
        mismatches.to_csv(out / "artifacts" / "differences.csv", index=False, encoding="utf-8-sig")
    result = {"browser": quality[0], "light": quality[1], "mismatches": len(mismatches),
              "note": "Ключ наблюдения snapshot_id + product_id; повторные обходы не увеличивают число уникальных товаров."}
    if persist:
        save_json(out / "artifacts" / "quality.json", result)
    if len(mismatches) or any(q["duplicate_observation_keys"] or q["nonpositive_prices"] or any(q["empty_shares"].values()) for q in quality):
        raise RuntimeError("Проверка качества/совпадения не пройдена")
    return result


def demo_timeout(out):
    artifacts = Path(out) / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    rules = robots_check(artifacts)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, **browser_proxy())
        context = make_context(browser)
        try:
            page = context.new_page()
            route_page(page, True, rules, {"blocked": 0})
            page.goto(URL, wait_until="domcontentloaded")
            try:
                page.get_by_test_id("intentional-missing-lab4").wait_for(timeout=300)
            except PWTimeout as exc:
                save_failure(page, artifacts, "controlled_timeout", str(exc))
                save_json(artifacts / "controlled_timeout.json", {"expected": True, "exit_code": 2, "timestamp": utc()})
                return 2
            raise RuntimeError("Контрольный таймаут неожиданно не возник")
        finally:
            context.close()
            browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["diagnose", "browser", "light", "check", "demo-timeout"])
    parser.add_argument("--out", type=Path, default=ROOT)
    parser.add_argument("--snapshots", type=int, default=1)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--rounds", type=int, default=24)
    parser.add_argument("--pause", type=float, default=1.0)
    parser.add_argument("--block-media", action="store_true")
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()
    if min(args.snapshots, args.limit, args.rounds) < 1 or args.pause < 1:
        parser.error("Положительные лимиты; пауза не меньше 1 с")
    try:
        if args.command == "diagnose":
            result = diagnose(args.out)
        elif args.command == "browser":
            result = browser_run(args.out, args.snapshots, args.block_media, args.limit, args.rounds, args.pause, args.benchmark)
        elif args.command == "light":
            result = light_run(args.out, args.snapshots, args.limit, args.rounds, args.pause)
        elif args.command == "check":
            result = check(args.out)
        else:
            return demo_timeout(args.out)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        save_json(args.out / "artifacts" / "fatal_error.json", {"command": args.command, "error": str(exc), "timestamp": utc()})
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
