import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .files import read_json, utc_now, write_json
from .http import SourceError, checked_document


class CheckpointPause(RuntimeError):
    pass


def parse_index(body, url):
    soup = BeautifulSoup(body, "html.parser")
    categories = [
        urljoin(url, link["href"])
        for link in soup.select(".side_categories ul ul a[href]")
    ]
    cards = soup.select("article.product_pod")
    if not categories or not cards:
        raise ValueError("нет ссылок на категории или карточек")
    for category in categories:
        path = urlsplit(category).path
        if not re.fullmatch(r"/catalogue/category/books/[^/]+_\d+/index\.html", path):
            raise ValueError("неизвестная ссылка на категорию")
    item = cards[0].select_one("h3 a[title]")
    price = cards[0].select_one("p.price_color")
    if item is None or price is None:
        raise ValueError("в первой карточке отсутствуют название или цена")
    needle = item["title"]
    return {
        "categories": list(dict.fromkeys(categories)),
        "cards": len(cards),
        "needle": needle,
        "needle_in_raw_html": needle in body,
        "price_raw": price.get_text(strip=True),
        "browser_required": False,
    }


def parse_page(body, url):
    soup = BeautifulSoup(body, "html.parser")
    heading = soup.select_one(".page-header h1")
    cards = soup.select("article.product_pod")
    if not heading or not cards:
        raise ValueError("нет названия категории или карточек")
    category = heading.get_text(" ", strip=True)
    if not category:
        raise ValueError("пустое название категории")
    products = []
    for card in cards:
        link = card.select_one("h3 a")
        price = card.select_one("p.price_color")
        stars = card.select_one("p.star-rating")
        stock = card.select_one("p.availability")
        detail = urljoin(url, link.get("href", "")) if link and link.get("href") else ""
        catalogue_id = re.search(r"_(\d+)/index\.html$", urlsplit(detail).path)
        products.append({
            "source_id": catalogue_id.group(1) if catalogue_id else None,
            "title_raw": link.get("title") or link.get_text(" ") if link else None,
            "category_raw": category,
            "price_raw": price.get_text() if price else None,
            "rating_raw": stars.get("class", []) if stars else None,
            "stock_raw": stock.get_text() if stock else None,
            "product_url": detail,
        })
    next_link = soup.select_one("li.next a[href]")
    next_url = urljoin(url, next_link["href"]) if next_link else None
    if next_url is not None:
        base = urlsplit(url)
        next_page = urlsplit(next_url)
        if (base.scheme, base.netloc) != (next_page.scheme, next_page.netloc) or not re.fullmatch(
            re.escape(base.path.rsplit("/", 1)[0]) + r"/page-\d+\.html", next_page.path
        ):
            raise ValueError("пагинация вышла за пределы категории")
    return products, next_url


def collect_catalogue(client, store, options, root: Path, *, full=False, page_budget=None):
    progress_file = root / "state" / "watermark.json"
    progress = read_json(progress_file, {})
    active = progress.get("full_scan")
    limit_expired = not progress.get("full_completed_at") or (
        datetime.now(timezone.utc) - datetime.fromisoformat(progress["full_completed_at"])
        >= timedelta(days=options["full_scan_days"])
    )
    start_full = full or limit_expired or progress.get("refresh_required") or not progress.get("pages")
    index_url = options["url"]
    if active:
        client.log.log("resume_catalogue", completed=len(active["done"]), pending=len(active["pending"]))
    else:
        index, envelope, status = checked_document(client, store, "books", index_url, parse_index)
        diagnostic = {
            "url": index_url,
            "status": 200,
            "response_bytes_utf8": len(envelope["payload"].encode("utf-8")),
            "sha256": envelope["_sha256"],
            **{key: value for key, value in index.items() if key != "categories"},
            "category_count": len(index["categories"]),
        }
        write_json(root / "reports" / "html_diagnostic.json", diagnostic)
        client.log.log("catalogue_index", status=status, categories=len(index["categories"]))
        if progress.get("categories") != index["categories"]:
            start_full = True
        if start_full:
            active = {"done": [], "pending": index["categories"].copy(), "next": {}}
            progress.update(full_scan=active, categories=index["categories"], refresh_required=False)
            write_json(progress_file, progress)

    touched = 0
    if active:
        while active["pending"]:
            url = active["pending"][0]
            if len(active["done"]) >= options["max_pages"]:
                raise SourceError("Достигнут защитный предел страниц каталога")
            (products, next_url), _, status = checked_document(client, store, "books", url, parse_page)
            active["pending"].pop(0)
            active["done"].append(url)
            active["next"][url] = next_url
            if next_url is not None:
                if next_url in active["done"] or next_url in active["pending"]:
                    raise SourceError("Обнаружен повтор страницы пагинации")
                active["pending"].insert(0, next_url)
            write_json(progress_file, progress)
            touched += 1
            client.log.log("catalogue_page", url=url, status=status, records=len(products),
                           completed=len(active["done"]), pending=len(active["pending"]))
            if page_budget is not None and touched >= page_budget and active["pending"]:
                raise CheckpointPause(f"Остановка после {touched} страниц. Очередь сохранена.")
        progress.update(pages=active["done"], next=active["next"], full_scan=None,
                        cursor=0, full_completed_at=utc_now(), refresh_required=False)
        write_json(progress_file, progress)
        return progress["pages"], {"scan": "full", "checked_pages": touched, "deferred_pages": 0}

    urls = progress["pages"]
    count = min(len(urls), options["recheck_pages"])
    cursor = progress["cursor"] % len(urls)
    for offset in range(count):
        url = urls[(cursor + offset) % len(urls)]
        (products, next_url), _, status = checked_document(client, store, "books", url, parse_page)
        if next_url != progress["next"].get(url):
            progress["refresh_required"] = True
            write_json(progress_file, progress)
            raise SourceError("Изменилась пагинация. Следующий запуск выполнит полный обход.")
        client.log.log("catalogue_page", url=url, status=status, records=len(products))
        progress["cursor"] = (cursor + offset + 1) % len(urls)
        write_json(progress_file, progress)
    return urls, {"scan": "incremental", "checked_pages": count, "deferred_pages": len(urls) - count}


def catalogue_rows(store, urls):
    rows = []
    for url in urls:
        envelope = store.latest[url]
        page_rows, _ = parse_page(envelope["payload"], url)
        for row in page_rows:
            rows.append({**row, "source": "books", "source_url": url,
                         "collected_at": envelope["_collected_at"],
                         "parser_version": store.parser_version})
    return rows
