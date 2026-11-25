from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from time import monotonic
from uuid import uuid4

from .files import append_jsonl, utc_now, write_json


def percentile_95(values):
    ordered = sorted(values)
    rank = (len(ordered) * 95 + 99) // 100
    return ordered[rank - 1] if rank else None


class RunLog:
    def __init__(self, root: Path, mode: str):
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        self.run_id = f"{timestamp}-{uuid4().hex[:8]}"
        self.root = root
        self.path = root / "logs" / f"run_{self.run_id}.jsonl"
        self.begun = monotonic()
        self.mode = mode
        self.requests = []
        self.events = Counter()

    def log(self, event: str, **fields):
        row = {"ts": utc_now(), "run_id": self.run_id, "event": event, **fields}
        append_jsonl(self.path, row)
        self.events[event] += 1
        if event == "request":
            self.requests.append(row)

    def incident(self, source, url, reason, status, body):
        path = self.root / "logs" / "incidents" / f"{self.run_id}_{source}_{self.events['incident'] + 1:02}.json"
        write_json(path, {"source": source, "url": url, "reason": reason, "status": status, "body": body})
        self.log("incident", source=source, url=url, reason=reason, status=status,
                 file=path.relative_to(self.root).as_posix())

    def summary(self, **extra):
        requests = self.requests
        elapsed = [row["ms"] for row in requests]
        codes = Counter(str(row["status"]) if row["status"] is not None else "network" for row in requests)
        failures = sum(not row["accepted"] for row in requests)
        limited = sum(row["status"] in (403, 429) for row in requests)
        return {
            "run_id": self.run_id,
            "mode": self.mode,
            "requests": len(requests),
            "codes": dict(sorted(codes.items())),
            "error_share": round(failures / max(1, len(requests)), 6),
            "limit_or_block_share": round(limited / max(1, len(requests)), 6),
            "retries": sum(row["attempt"] > 1 for row in requests),
            "median_ms": median(elapsed) if elapsed else None,
            "p95_ms": percentile_95(elapsed),
            "wire_body_bytes": sum(row["wire_bytes"] for row in requests),
            "decoded_body_bytes": sum(row["decoded_bytes"] for row in requests),
            "bytes_saved_304": sum(row["saved_304_bytes"] for row in requests),
            "bytes_saved_gzip": sum(max(0, row["decoded_bytes"] - row["wire_bytes"])
                                    for row in requests if row["encoding"] == "gzip"),
            "breaker_opened": self.events["circuit_open"],
            "duration_s": round(monotonic() - self.begun, 3),
            "log": self.path.relative_to(self.root).as_posix(),
            **extra,
        }

    def save_report(self, report):
        file = self.root / "reports" / f"run_report_{self.run_id}.json"
        write_json(file, report)
        return file


def alert_report(report, settings):
    warnings = []
    for metric in ("error_share", "limit_or_block_share", "volume_change", "p95_ms"):
        value = report.get(metric)
        threshold = settings.get(metric)
        if value is not None and threshold is not None and value > threshold:
            warnings.append({"metric": metric, "value": value, "threshold": threshold, "level": "warning"})
    if report.get("mode") == "incremental" and report.get("new_products") == settings["no_new_records"]:
        warnings.append({"metric": "no_new_records", "value": 0, "threshold": 0, "level": "info"})
    if report.get("status") in ("degraded", "red"):
        warnings.append({"metric": "pipeline_status", "value": report["status"], "level": "error"})
    return warnings
