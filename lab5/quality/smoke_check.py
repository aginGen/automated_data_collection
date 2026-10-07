import argparse
import json
from pathlib import Path
import sys


def check(previous: dict, current: dict) -> list[str]:
    warnings = []
    if previous["rows"] and current["rows"] < previous["rows"] * 0.8:
        warnings.append(f"Количество записей упало: {previous['rows']} -> {current['rows']}")
    if current["required_empty_share"] > 0.05:
        warnings.append(f"Пустые обязательные поля: {current['required_empty_share']:.2%}")
    return warnings


def main():
    parser = argparse.ArgumentParser(description='Предупреждение о падении объёма и пустых обязательных полях.')
    parser.add_argument("previous", type=Path)
    parser.add_argument("current", type=Path)
    args = parser.parse_args()
    warnings = check(json.loads(args.previous.read_text(encoding="utf-8")),
                     json.loads(args.current.read_text(encoding="utf-8")))
    if warnings:
        print("\n".join("WARNING: " + message for message in warnings))
        return 1
    print("Smoke-check: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
