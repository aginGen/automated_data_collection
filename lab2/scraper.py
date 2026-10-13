from __future__ import annotations

import argparse
import csv
import html
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://books.toscrape.com/"
START_URL = urljoin(BASE_URL, "catalogue/page-1.html")
RATING_VALUES = {
    "One": 1,
    "Two": 2,
    "Three": 3,
    "Four": 4,
    "Five": 5,
}


@dataclass(frozen=True)
class Book:
    title: str
    category: str
    price_gbp: float
    rating: int
    url: str
    upc: str


def clean_text(value: str) -> str:
    return " ".join(value.split())


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = "university-data-mining-lab/2.0"
    return session


def get_soup(
    session: requests.Session, url: str, timeout: float, retries: int = 2
) -> BeautifulSoup:
    for attempt in range(retries + 1):
        try:
            with session.get(url, timeout=timeout) as response:
                response.raise_for_status()
                response.encoding = response.apparent_encoding
                return BeautifulSoup(response.text, "html.parser")
        except (
            requests.Timeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
            requests.HTTPError,
        ) as error:
            if isinstance(error, requests.HTTPError) and (
                error.response is None
                or error.response.status_code not in (429, 500, 502, 503, 504)
            ):
                raise
            if attempt == retries:
                raise
            time.sleep(0.5 * 2**attempt)
    raise RuntimeError("Не выполнена ни одна попытка запроса")


def parse_rating(classes: Iterable[str]) -> int:
    for class_name in classes:
        if class_name in RATING_VALUES:
            return RATING_VALUES[class_name]
    raise ValueError("Не найден класс рейтинга")


def parse_detail(
    session: requests.Session, url: str, timeout: float, retries: int = 2
) -> tuple[str, str]:
    soup = get_soup(session, url, timeout, retries)


    crumbs = soup.select("ul.breadcrumb li")
    category = clean_text(crumbs[-2].get_text()) if len(crumbs) >= 3 else ""

    values = {
        clean_text(row.th.get_text()): clean_text(row.td.get_text())
        for row in soup.select("table.table.table-striped tr")
        if row.th is not None and row.td is not None
    }
    return category, values.get("UPC", "")


def scrape_books(limit: int, timeout: float, retries: int) -> list[Book]:
    unique: dict[str, Book] = {}
    page_url: str | None = START_URL

    with build_session() as session:
        while page_url and len(unique) < limit:
            soup = get_soup(session, page_url, timeout, retries)
            for card in soup.select("article.product_pod"):
                link = card.select_one("h3 a")
                price = card.select_one("p.price_color")
                rating = card.select_one("p.star-rating")
                if link is None or price is None or rating is None:
                    continue

                detail_url = urljoin(page_url, str(link.get("href", "")))
                category, upc = parse_detail(session, detail_url, timeout, retries)
                price_match = re.search(r"\d+(?:\.\d+)?", price.get_text())
                if price_match is None:
                    continue

                book = Book(
                    title=clean_text(str(link.get("title", link.get_text()))),
                    category=category,
                    price_gbp=float(price_match.group()),
                    rating=parse_rating(rating.get("class", [])),
                    url=detail_url,
                    upc=upc,
                )

                unique.setdefault(book.upc or book.url, book)
                if len(unique) >= limit:
                    break

            next_link = soup.select_one("li.next a")
            page_url = urljoin(page_url, str(next_link["href"])) if next_link else None

    return list(unique.values())


def save_csv(books: list[Book], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(Book.__annotations__))
        writer.writeheader()
        writer.writerows(asdict(book) for book in books)


def save_html_preview(books: list[Book], output: Path) -> None:
    headers = list(Book.__annotations__)
    head = "".join(f"<th>{html.escape(name)}</th>" for name in headers)
    body = "\n".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(asdict(book)[name]))}</td>" for name in headers
        )
        + "</tr>"
        for book in books
    )
    document = f"""<!doctype html>
<html lang="ru"><meta charset="utf-8"><title>Результат сбора данных</title>
<style>
body {{ font: 14px Arial, sans-serif; margin: 24px; color: #1f2937; }}
h1 {{ margin-bottom: 6px; }} p {{ color: #4b5563; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #cbd5e1; padding: 7px; text-align: left; }}
th {{ background: #e2e8f0; position: sticky; top: 0; }}
tr:nth-child(even) {{ background: #f8fafc; }}
td:nth-child(3), td:nth-child(4) {{ text-align: right; }}
</style>
<h1>Books to Scrape — результат</h1>
<p>Строк: {len(books)} · Полей: {len(headers)} · Доля пропусков: {missing_share(books):.2%}</p>
<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></html>"""
    output.write_text(document, encoding="utf-8")


def missing_share(books: list[Book]) -> float:
    if not books:
        return 0.0
    values = [value for book in books for value in asdict(book).values()]
    missing = sum(value is None or value == "" for value in values)
    return missing / len(values)


def print_summary(books: list[Book]) -> None:
    print(f"Число строк: {len(books)}")
    print(f"Доля пропусков: {missing_share(books):.2%}")
    print("Первые пять записей:")
    for book in books[:5]:
        print(asdict(book))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Сбор каталога учебного сайта Books to Scrape в CSV.')
    parser.add_argument("--limit", type=int, default=40, help="число книг (не менее 20)")
    parser.add_argument("--timeout", type=float, default=10.0, help="тайм-аут запроса")
    parser.add_argument("--retries", type=int, default=2, help="повторные попытки")
    parser.add_argument("--output", type=Path, default=Path("books.csv"))
    parser.add_argument(
        "--preview", type=Path, default=Path("result_preview.html"),
        help="HTML-предпросмотр итоговой таблицы",
    )
    args = parser.parse_args()
    if args.limit < 20:
        parser.error("--limit должен быть не меньше 20")
    if args.timeout <= 0:
        parser.error("--timeout должен быть положительным")
    if args.retries < 2:
        parser.error("--retries должен быть не меньше 2")
    return args


def main() -> None:
    args = parse_args()
    books = scrape_books(args.limit, args.timeout, args.retries)
    if len(books) < 20:
        raise RuntimeError(f"Получено только {len(books)} записей")
    save_csv(books, args.output)
    save_html_preview(books, args.preview)
    print_summary(books)


if __name__ == "__main__":
    main()
