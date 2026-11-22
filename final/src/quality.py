from collections import Counter
from dataclasses import dataclass
from datetime import date

from .clean import CleanData


@dataclass
class Quality:
    status: str
    metrics: list[dict]
    failures: list[str]


def latest_rate(data: CleanData, as_of: date):
    return max((rate for rate in data.rates if rate.rate_date <= as_of),
               key=lambda rate: rate.rate_date, default=None)


def evaluate(data: CleanData, as_of: date, previous_count, settings, minimum_products):
    count = len(data.books)
    rate = latest_rate(data, as_of)
    mandatory = ("business_key", "title", "category", "price_pence", "currency", "collected_at")
    completeness = sum(all(getattr(book, field) not in (None, "") for field in mandatory) for book in data.books)
    keys = {book.business_key for book in data.books}
    volume = abs(count - previous_count) / max(1, previous_count) if previous_count is not None else 0.0
    values = {
        "required_completeness": completeness / max(1, count),
        "unique_keys": len(keys) / max(1, count),
        "contract_validity": data.valid_before_dedup / max(1, data.raw_records),
        "reject_share": len(data.rejects) / max(1, data.raw_records),
        "fx_coverage": sum(rate is not None and book.currency == rate.currency for book in data.books) / max(1, count),
        "volume_change": volume,
        "optional_completeness": sum(book.rating is not None and book.in_stock is not None for book in data.books)
        / max(1, count),
        "fx_age_days": (as_of - rate.rate_date).days if rate else None,
    }
    metrics = []
    for name, value in values.items():
        thresholds = settings[name]
        state = "red"
        if value is not None:
            at_least = thresholds["direction"] == "min"
            if (value >= thresholds["green"] if at_least else value <= thresholds["green"]):
                state = "green"
            elif (value >= thresholds["yellow"] if at_least else value <= thresholds["yellow"]):
                state = "yellow"
        metrics.append({"metric": name, "value": value, "status": state, **thresholds})
    failures = [metric["metric"] for metric in metrics if metric["status"] == "red"]
    if count < minimum_products:
        failures.append(f"minimum_products: {count} < {minimum_products}")
    status = "red" if failures else "yellow" if any(row["status"] == "yellow" for row in metrics) else "green"
    return Quality(status, metrics, failures)


def reject_summary(data: CleanData):
    return dict(Counter(
        f"{row['stage']}:{reason['field']}"
        for row in data.rejects for reason in row["reasons"]
    ))
