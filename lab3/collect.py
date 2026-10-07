from __future__ import annotations

import argparse
import csv
import random
import threading
from email.utils import parsedate_to_datetime
from typing import Callable

import psutil
import requests
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


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


def paginate(client: APIClient, url: str, extract: Callable, make_params: Callable,
             page_size: int, max_records: int, max_pages: int,
             total: Callable | None = None) -> list[dict]:
    if min(page_size, max_records, max_pages) <= 0:
        raise ValueError("Предохранители пагинации должны быть положительными")
    records: list[dict] = []
    offset = 0
    for page in range(1, max_pages + 1):
        limit = min(page_size, max_records - len(records))
        payload, _ = client.get_json(url, make_params(page, offset, limit), page,
                                     count=lambda body: len(extract(body)))
        batch = extract(payload)
        if not isinstance(batch, list):
            raise APIError("Массив записей отсутствует в ответе")
        if not batch:
            break
        records.extend(batch[:max_records - len(records)])
        offset += len(batch)
        if len(records) >= max_records or (total and offset >= total(payload)):
            break
    return records


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
SEARCH_URL = "https://openlibrary.org/search.json"
FIELDS = "key,title,author_key,author_name,first_publish_year,language,edition_count"
REQUIRED = ["work_id", "title", "url", "edition_count"]


def normalize_books(raw: list[dict], author_cache: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    books = pd.json_normalize(raw, sep="_")
    flat = pd.DataFrame({
        "work_id": books["key"],
        "title": books["title"].map(lambda value: " ".join(str(value).split())),
        "first_publish_year": pd.to_numeric(books.get("first_publish_year"), errors="coerce").astype("Int64"),
        "edition_count": pd.to_numeric(books["edition_count"], errors="coerce").astype("Int64"),
        "author_key": [row.get("author_key", [""])[0] if row.get("author_key") else "" for row in raw],
        "author_name_catalogue": [row.get("author_name", [""])[0] if row.get("author_name") else "" for row in raw],
        "author_count": [len(row.get("author_key", [])) for row in raw],
        "language_count": [len(row.get("language", [])) for row in raw],
        "languages": [";".join(row.get("language", [])) for row in raw],
        "collected_at": [row["collected_at"] for row in raw],
    })
    flat["url"] = "https://openlibrary.org" + flat["work_id"]
    author_rows = [{
        "author_key": key,
        "author_name_verified": value.get("name"),
        "author_revision": value.get("revision"),
        "author_modified_at": value.get("last_modified", {}).get("value"),
        "author_url": "https://openlibrary.org/authors/" + key,
    } for key, value in author_cache.items()]
    authors = pd.json_normalize(author_rows, sep="_")
    if authors.empty:
        authors = pd.DataFrame(columns=["author_key", "author_name_verified", "author_revision",
                                       "author_modified_at", "author_url"])
    before = len(flat)
    flat = flat.merge(authors, on="author_key", how="left", validate="many_to_one", indicator=True)
    if len(flat) != before:
        raise ValueError("Обогащение изменило число книг")
    flat["author_matched"] = flat.pop("_merge").eq("both")
    flat["collected_at"] = pd.to_datetime(flat["collected_at"], utc=True, errors="raise")
    flat["author_modified_at"] = pd.to_datetime(flat["author_modified_at"], utc=True, errors="coerce", format="mixed")
    flat["author_revision"] = pd.to_numeric(flat["author_revision"], errors="coerce").astype("Int64")
    language_rows = [{**row, "language": row.get("language", [])} for row in raw]
    languages = pd.json_normalize(language_rows, record_path="language",
                                  meta=["key", "title"], errors="ignore", sep="_")
    languages = languages.rename(columns={0: "language", "key": "work_id"})
    languages = languages.drop_duplicates(["work_id", "language"])
    return flat, languages


def quality(books: pd.DataFrame) -> dict:
    current_year = datetime.now(timezone.utc).year
    checks = {
        "edition_count_positive": books["edition_count"].gt(0).fillna(False),
        "publication_year_not_future": books["first_publish_year"].le(current_year) | books["first_publish_year"].isna(),
        "valid_work_key": books["work_id"].str.fullmatch(r"/works/OL\d+W"),
        "nonempty_title": books["title"].str.strip().ne(""),
    }
    complete = {
        name: round(float((column.notna() & column.astype(str).str.strip().ne("")).mean() * 100), 2)
        for name, column in books.items()
    }
    return {
        "rows": len(books),
        "unique_keys": books["work_id"].nunique(),
        "duplicates": int(books.duplicated("work_id").sum()),
        "completeness_percent": complete,
        "required_empty_rows": int(books[REQUIRED].isna().any(axis=1).sum()),
        "business_rule_violations": {name: int((~values).sum()) for name, values in checks.items()},
        "author_matches": int(books["author_matched"].sum()),
        "types": {name: str(dtype) for name, dtype in books.dtypes.items()},
    }


def save_frame(frame: pd.DataFrame, path: Path) -> None:
    output = frame.copy()
    for name in output:
        if isinstance(output[name].dtype, pd.DatetimeTZDtype):
            output[name] = output[name].map(lambda value: value.isoformat() if pd.notna(value) else None)
    rows = output.astype(object).where(output.notna(), None).to_dict("records")
    write_csv(path, rows, list(output.columns))


def collect(output: Path = ROOT, query: str = "python programming",
            page_size: int = 90, max_records: int = 360, max_pages: int = 20,
            run_label: str = "initial", interval: float = 1.1) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    state_path = output / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {
        "query": query, "seen_work_ids": [], "watermark": None,
    }
    if state["query"] != query:
        raise ValueError("Для другого поискового запроса используйте отдельную папку --output")
    old_raw = []
    raw_path = output / "data_raw.jsonl"
    if raw_path.exists():
        old_raw = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines() if line]
    old_ids = {row["key"] for row in old_raw}
    if old_ids != set(state["seen_work_ids"]):
        raise ValueError("Файл состояния не соответствует сохранённым сырым данным")
    cache_path = output / "authors_cache.json"
    author_cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    started = time.perf_counter()
    with MemorySampler() as memory, APIClient(interval=interval) as client:
        try:
            fetched = paginate(
                client, SEARCH_URL, lambda body: body["docs"],
                lambda page, offset, limit: {"q": query, "offset": offset, "limit": limit,
                                            "fields": FIELDS, "sort": "key"},
                page_size, max_records, max_pages, total=lambda body: int(body["numFound"]),
            )
            new = {row["key"]: row for row in fetched if row["key"] not in old_ids}
            for row in new.values():
                row["collected_at"] = datetime.now(timezone.utc).isoformat()
            raw = old_raw + list(new.values())
            keys = sorted({
                row["author_key"][0] for row in raw if row.get("author_key")
            } - set(author_cache))
            for index, key in enumerate(keys, 1):
                body, _ = client.get_json(f"https://openlibrary.org/authors/{key}.json",
                                         page=0, count=lambda body: 1)
                author_cache[key] = {
                    name: body[name] for name in ["key", "name", "revision", "last_modified", "type"]
                    if name in body
                }
                write_json(cache_path, author_cache)
                if index % 25 == 0:
                    print(f"Authors: {index}/{len(keys)}", flush=True)
            books, languages = normalize_books(raw, author_cache)
            report = quality(books)
            if report["duplicates"] or report["required_empty_rows"]:
                raise ValueError("Проверка ключей или обязательных полей не пройдена")
            if len(books) < 300:
                raise ValueError(f"Получено {len(books)} книг, требуется не менее 300")
            if new:
                temporary = raw_path.with_suffix(".jsonl.tmp")
                temporary.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in raw) + "\n", encoding="utf-8")
                temporary.replace(raw_path)
                save_frame(books, output / "data_clean.csv")
                save_frame(languages, output / "book_languages.csv")
                write_json(state_path, {
                    "query": query,
                    "seen_work_ids": sorted(old_ids | new.keys()),
                    "watermark": {"last_completed_offset": len(fetched), "last_work_id": fetched[-1]["key"]},
                })
            write_json(output / "quality.json", report)
            write_csv(output / "completeness.csv", [
                {"field": field, "completeness_percent": value}
                for field, value in report["completeness_percent"].items()
            ])
            result = {
                "run": run_label, "query": query, "fetched": len(fetched),
                "new_records": len(new), "total_rows": len(books),
                "search_pages": sum(row["page"] > 0 and row["status"] == 200 for row in client.logs),
                "language_rows": len(languages), "merge_rows_before": len(raw),
                "merge_rows_after": len(books),
                "duration_s": round(time.perf_counter() - started, 4),
                **client.metrics(),
            }
        finally:
            client.save_log(output / f"collection_log{'' if run_label == 'initial' else '_' + run_label}.csv")
    result["peak_memory_mib"] = memory.peak_mib
    write_json(output / f"metrics_{run_label}.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description='Вариант 3: книги Open Library Search и сведения Open Library Authors.')
    parser.add_argument("--query", default="python programming")
    parser.add_argument("--page-size", type=int, default=90)
    parser.add_argument("--max-records", type=int, default=360)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--output", type=Path, default=ROOT)
    parser.add_argument("--run-label", default="initial")
    parser.add_argument("--interval", type=float, default=1.1)
    args = parser.parse_args()
    if args.max_records < 300 or args.max_pages < 3 or args.interval < 1:
        parser.error("Требуются max-records >= 300, max-pages >= 3 и interval >= 1")
    collect(args.output, args.query, args.page_size, args.max_records, args.max_pages,
            args.run_label, args.interval)


if __name__ == "__main__":
    main()
