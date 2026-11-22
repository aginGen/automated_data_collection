import argparse
import copy
import json
import os
import sqlite3
import sys
from contextlib import closing, nullcontext
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import yaml
from filelock import FileLock, Timeout

from .clean import normalize_and_validate
from .collect_api import collect_rates, fx_rows
from .collect_html import CheckpointPause, catalogue_rows, collect_catalogue
from .demo import failing_fx
from .files import PROJECT, read_json, write_json
from .http import HttpClient, SourceError
from .mart import build_mart, export_clean
from .observability import RunLog, alert_report
from .quality import evaluate, latest_rate, reject_summary
from .raw_store import RawStore
from .storage import demonstrate_upsert, load_warehouse, open_warehouse


def config(path):
    options = yaml.safe_load(path.read_text(encoding="utf-8"))
    options["project"]["contact"] = os.getenv("FINAL_CONTACT") or options["project"]["contact"]
    contact = urlsplit(options["project"]["contact"])
    if contact.scheme not in ("https", "mailto") or any(ch.isspace() for ch in options["project"]["contact"]):
        raise ValueError("Контакт должен быть адресом HTTPS или mailto без пробелов")
    if options["project"]["minimum_products"] < 500:
        raise ValueError("Для проекта задан минимальный объём 500 книг")
    defaults = {
        "books": "https://books.toscrape.com/",
        "fx": "https://www.cbr-xml-daily.ru/daily_json.js",
    }
    for name, url in defaults.items():
        if options["sources"][name]["url"] != url:
            raise ValueError(f"Источник {name} отличается от утверждённого")
        rate = options["sources"][name]["requests_per_second"]
        if not 0 < rate <= (0.5 if name == "fx" else 1):
            raise ValueError(f"Слишком высокая частота запросов к {name}")
    return options


def snapshots(root, log, project):
    return RawStore(root, project["parser_version"], log.run_id)


def data_from_raw(store, page_urls, sources):
    return normalize_and_validate(catalogue_rows(store, page_urls), fx_rows(store, sources["fx"]["currency"]))


def existing_products(path):
    if not path.is_file():
        return None
    with closing(sqlite3.connect(path)) as db:
        return db.execute("SELECT count(*) FROM products").fetchone()[0]


def save_rejects(path, rows):
    target = path.with_suffix(".jsonl.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("w", encoding="utf-8", newline="\n") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        target.replace(path)
    finally:
        target.unlink(missing_ok=True)


def collect(args, log, store, project, settings, sources, root):
    problems = {}
    source_config = copy.deepcopy(sources)
    scope = failing_fx() if args.simulate_api_failure else nullcontext(None)
    with scope as mock_url:
        if mock_url is not None:
            source_config["fx"]["url"] = mock_url
            log.log("simulated_outage", source="fx", url=mock_url)
        with HttpClient(settings, source_config, project["contact"], log) as client:
            try:
                collect_rates(client, store, source_config["fx"])
            except SourceError as exc:
                problems["fx"] = str(exc)
                log.log("source_failed", source="fx", reason=str(exc))
            try:
                pages, scan = collect_catalogue(client, store, source_config["books"], root,
                                               full=args.mode == "full", page_budget=args.page_budget)
            except SourceError as exc:
                problems["books"] = str(exc)
                log.log("source_failed", source="books", reason=str(exc))
                pages, scan = [], {}
            checks = {host: result for host, (_, _, result) in client.robots.items()}
    if mock_url is None:
        write_json(root / "reports" / "robots.json", checks)
    return pages, scan, problems


def pipeline(args, options, root, log):
    project, sources = options["project"], options["sources"]
    as_of = datetime.now(ZoneInfo("Europe/Moscow")).date()
    store = snapshots(root, log, project)
    before = store.raw_counts()
    warehouse = root / "db" / "warehouse.db"
    previous_count = existing_products(warehouse)
    scan = {}
    collect_errors = {}
    if args.mode in ("full", "incremental"):
        pages, scan, collect_errors = collect(args, log, store, project, options["http"], sources, root)
        if collect_errors:
            return 2, {"status": "degraded", "sources_failed": collect_errors, **scan,
                       "raw_before": before, "raw_after": store.raw_counts(), "mart_written": False}
    else:
        pages = read_json(root / "state" / "watermark.json", {}).get("pages", [])
        if not pages:
            raise ValueError("Нет завершённого снимка каталога для чтения из raw")
        as_of = max(datetime.fromisoformat(item["_collected_at"]).astimezone(ZoneInfo("Europe/Moscow")).date()
                    for item in store.latest.values())
    data = data_from_raw(store, pages, sources)
    summary = {
        "products": len(data.books),
        "rates": len(data.rates),
        "rejected_records": len(data.rejects),
        "reject_causes": reject_summary(data),
        "normalized_records": data.raw_records,
        "duplicate_records": data.duplicate_count,
        "previous_products": previous_count,
        "raw_before": before,
        "raw_after": store.raw_counts(),
        **scan,
    }
    if args.mode == "verify-load":
        result = demonstrate_upsert(data)
        write_json(root / "reports" / "idempotency.json", result)
        log.log("upsert_verified", **result)
        return 0, {"status": "success", "mart_written": False, **summary, "idempotency": result}

    quality = evaluate(data, as_of, previous_count, options["quality"], project["minimum_products"])
    for metric in quality.metrics:
        summary[metric["metric"]] = metric["value"]
    log.log("quality_checked", status=quality.status, products=len(data.books), rejects=len(data.rejects),
             failures=quality.failures)
    quality_report = {"run_id": log.run_id, "quality_status": quality.status, "metrics": quality.metrics,
                      "quality_failures": quality.failures, "protocol": data.protocol}
    summary.update(quality_report, observation_date=as_of.isoformat())
    if quality.status == "red":
        bad_records = root / "reports" / f"rejects_{log.run_id}.jsonl"
        save_rejects(bad_records, data.rejects)
        return 2, {"status": "red", "mart_written": False, **summary}

    rate = latest_rate(data, as_of)
    with closing(open_warehouse(warehouse)) as db:
        loaded = load_warehouse(db, data.books, data.rates)
        export_clean(data, root)
        save_rejects(root / "clean" / "rejects.jsonl", data.rejects)
        write_json(root / "clean" / "quality.json", quality_report)
        analytics = build_mart(db, root, rate, project["budget_rub"], project["sensitivity_percent"])
    log.log("warehouse_loaded", **loaded)
    log.log("mart_published", products=analytics["products"], categories=analytics["categories"])
    return 0, {"status": "success", "mart_written": True, "upsert": loaded,
               "new_products": loaded["products"]["inserted"], "rate_date": rate.rate_date.isoformat(), **summary}


def cli():
    parser = argparse.ArgumentParser(description="Сбор каталога, курсов и пересчёт цен")
    parser.add_argument("--mode", choices=("full", "incremental", "rebuild", "verify-load"), default="incremental")
    parser.add_argument("--config", type=Path, default=PROJECT / "config.yaml")
    parser.add_argument("--data-root", type=Path, default=PROJECT)
    parser.add_argument("--page-budget", type=int)
    parser.add_argument("--simulate-api-failure", action="store_true")
    args = parser.parse_args()
    if args.page_budget is not None and (args.page_budget < 1 or args.mode != "full"):
        parser.error("--page-budget требует --mode full и положительное число")
    if args.simulate_api_failure and args.mode != "incremental":
        parser.error("--simulate-api-failure требует --mode incremental")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    root = args.data_root.resolve()
    (root / "state").mkdir(parents=True, exist_ok=True)
    options = config(args.config)
    log = RunLog(root, args.mode)
    log.log("run_started", mode=args.mode, user_agent_contact=options["project"]["contact"],
            simulation=args.simulate_api_failure)
    try:
        with FileLock(root / "state" / "run.lock", timeout=0):
            code, result = pipeline(args, options, root, log)
            clear_previous = code == 0 and result.get("mart_written")
            if clear_previous:
                write_json(root / "state" / "last_success.json", {"run_id": log.run_id, "mode": args.mode,
                                                                 "products": result["products"]})
    except (CheckpointPause, KeyboardInterrupt, Timeout) as exc:
        code = 3
        result = {"status": "paused", "reason": str(exc) if isinstance(exc, CheckpointPause)
                  else "Прогон прерван или уже выполняется", "mart_written": False}
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        code = 2
        result = {"status": "degraded", "reason": str(exc), "mart_written": False}
        log.log("run_failure", error=type(exc).__name__, reason=str(exc))
    log.log("run_finished", exit_code=code, status=result["status"])
    data = log.summary(exit_code=code, simulated_failure=args.simulate_api_failure, **result)
    data["alerts"] = alert_report(data, options["alerts"])
    report_file = log.save_report(data)
    compact = {key: data.get(key) for key in (
        "run_id", "status", "exit_code", "requests", "codes", "retries", "products", "rejected_records",
        "new_products", "duration_s", "quality_status", "quality_failures", "alerts", "upsert", "sources_failed",
        "reason"
    )}
    compact["report"] = report_file.relative_to(root).as_posix()
    print(json.dumps(compact, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(cli())
