import json
from datetime import datetime
from decimal import Decimal

from .http import checked_document


def parse_fx(body, url, currency):
    data = json.loads(body, parse_float=Decimal)
    quote = data["Valute"][currency]
    nominal = quote["Nominal"]
    if quote["CharCode"] != currency or nominal != 1:
        raise ValueError(f"Ожидалась котировка {currency} за одну единицу")
    rows = []
    for date_key, rate_key in (("PreviousDate", "Previous"), ("Date", "Value")):
        effective = datetime.fromisoformat(data[date_key]).date()
        rows.append({
            "currency": currency,
            "rate_date": effective.isoformat(),
            "nominal": nominal,
            "value_raw": str(quote[rate_key]),
            "quote_field": rate_key,
            "source_url": url,
        })
    if rows[0]["rate_date"] >= rows[1]["rate_date"]:
        raise ValueError("даты курсов не идут по возрастанию")
    return rows


def collect_rates(client, store, settings):
    url = settings["url"]
    currency = settings["currency"]
    _, _, status = checked_document(client, store, "fx", url, lambda body, address: parse_fx(body, address, currency))
    client.log.log("rates_collected", currency=currency, status=status)


def fx_rows(store, currency):
    latest = {}
    for envelope in store.fx_snapshots:
        for row in parse_fx(envelope["payload"], envelope["_source_url"], currency):
            latest[(row["currency"], row["rate_date"])] = {
                **row,
                "source": "fx",
                "collected_at": envelope["_collected_at"],
                "parser_version": store.parser_version,
            }
    return list(latest.values())
