import json, statistics
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path


class Log:
    def __init__(self, path, run):
        self.path = path
        self.run = run
        self.events = []

    def emit(
        self,
        event,
        host="",
        url="",
        status=None,
        ms=0,
        attempt=0,
        bytes=0,
        error=None,
        **extra
    ):
        d = dict(
            ts=datetime.now(timezone.utc).isoformat(),
            run_id=self.run,
            event=event,
            host=host,
            url=url,
            status=status,
            ms=round(ms, 3),
            attempt=attempt,
            bytes=bytes,
            error=error,
            **extra
        )
        self.events.append(d)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")


def summarize(log, duration, accepted, rejected, activations, history=None, *, profile=None, response_profile=None, representation_bytes=None):
    e = [x for x in log.events if x["event"] == "request"]
    n = len(e)
    statuses = Counter(str(x["status"]) for x in e)
    lat = sorted(x["ms"] for x in e)
    errors = sum(x["status"] is None or x["status"] >= 400 for x in e)
    m = dict(
        run_id=log.run,
        profile=profile,
        response_profile=response_profile,
        representation_bytes=representation_bytes,
        requests=n,
        statuses=dict(statuses),
        error_fraction=errors / n if n else 0,
        rate_429_403=sum(statuses.get(str(s), 0) for s in (429, 403)) / n if n else 0,
        retries=sum(x["attempt"] > 1 for x in e),
        p50_ms=statistics.median(lat) if lat else 0,
        p95_ms=lat[max(0, __import__("math").ceil(0.95 * n) - 1)] if lat else 0,
        wire_body_bytes=sum(x["bytes"] for x in e),
        responses_304=statuses.get("304", 0),
        breaker_activations=activations,
        accepted=accepted,
        rejected=rejected,
        duration_seconds=round(duration, 3),
        mean_body_bytes=sum(x["bytes"] for x in e) / n if n else 0,
    )
    entities = [x for x in e if x["status"] in (200, 304)]
    m["successful_resources"] = len(entities)
    m["normalized_mean_response_bytes"] = (
        representation_bytes / len(entities)
        if representation_bytes is not None and entities else None
    )
    m["mean_entity_bytes"] = (
        sum(x.get("entity_bytes", x["bytes"]) for x in entities) / len(entities)
        if entities
        else 0
    )
    alerts = []
    for name, condition in [
        ("errors>10%", m["error_fraction"] > 0.1),
        ("403/429>0%", m["rate_429_403"] > 0),
        ("p95>5000ms", m["p95_ms"] > 5000),
        ("retries>20%", m["retries"] > n * 0.2),
        ("breaker>0", activations > 0),
        ("zero_records", accepted == 0),
    ]:
        if condition:
            alerts.append(name)
    # Compare only explicitly equivalent datasets. Full reconstructed output,
    # not the wire size of a delta or compressed response, is the baseline.
    comparable = [x for x in (history or []) if profile and x.get("profile") == profile and x.get("successful_resources") == m["successful_resources"] and x.get("normalized_mean_response_bytes") is not None]
    if comparable:
        med = statistics.median(x["accepted"] for x in comparable)
        size = statistics.median(x["normalized_mean_response_bytes"] for x in comparable)
        if med and abs(accepted - med) / med > 0.2:
            alerts.append("records_deviation>20%")
        if size and m["normalized_mean_response_bytes"] is not None and abs(m["normalized_mean_response_bytes"] - size) / size > 0.3:
            alerts.append("size_deviation>30%")
    response_history = [x for x in (history or []) if profile and response_profile and x.get("profile") == profile and x.get("response_profile") == response_profile and x.get("successful_resources") == m["successful_resources"] and x.get("mean_entity_bytes", 0) > 0]
    m["response_history_count"] = len(response_history)
    if response_history and entities:
        size = statistics.median(x["mean_entity_bytes"] for x in response_history)
        if abs(m["mean_entity_bytes"] - size) / size > 0.3:
            alerts.append("response_size_deviation>30%")
    m["alerts"] = alerts
    m["status"] = "red" if alerts else "green"
    return m
