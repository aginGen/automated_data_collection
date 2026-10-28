"""Compare two independent crawl snapshots; exit 1 on data degradation."""

import argparse
import json
import math
from pathlib import Path


def validate(snapshot):
    if not isinstance(snapshot, dict):
        raise ValueError("Snapshot must be a JSON object")
    rows = snapshot.get("rows")
    share = snapshot.get("required_empty_share")
    if isinstance(rows, bool) or not isinstance(rows, int) or rows < 0:
        raise ValueError("rows must be a nonnegative integer")
    if (isinstance(share, bool) or not isinstance(share, (int, float))
            or not math.isfinite(share) or not 0 <= share <= 1):
        raise ValueError("required_empty_share must be a finite fraction in [0, 1]")
    if not snapshot.get("scope"):
        raise ValueError("scope must identify the source and collection window")


def check(previous, current):
    validate(previous)
    validate(current)
    if previous["scope"] != current["scope"]:
        raise ValueError("Cannot compare different sources or collection windows")
    warnings = []
    # Strict boundaries: exactly 20% fewer rows and exactly 5% empties pass.
    if previous["rows"] and current["rows"] < previous["rows"] * 0.8:
        warnings.append(f"Число записей упало более чем на 20%: {previous['rows']} -> {current['rows']}")
    if current["required_empty_share"] > 0.05:
        warnings.append(f"Пустые обязательные поля: {current['required_empty_share']:.2%} (>5%)")
    return warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("previous", type=Path)
    parser.add_argument("current", type=Path)
    args = parser.parse_args()
    try:
        previous = json.loads(args.previous.read_text(encoding="utf-8-sig"))
        current = json.loads(args.current.read_text(encoding="utf-8-sig"))
        warnings = check(previous, current)
    except (OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}")
        return 2
    for warning in warnings:
        print("WARNING: " + warning)
    if not warnings:
        print("Smoke-check: OK")
    return 1 if warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())
