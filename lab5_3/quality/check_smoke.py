"""Executable boundary checks for the required early warning thresholds."""

import json
from pathlib import Path
import tempfile

from analyze import summarize
from smoke_check import check


def main():
    base = {"scope": "test:equal-window", "rows": 100, "required_empty_share": 0}
    cases = [
        ("unchanged", dict(base), 0),
        ("exactly_20_percent_fewer", dict(base, rows=80), 0),
        ("more_than_20_percent_fewer", dict(base, rows=79), 1),
        ("exactly_5_percent_missing", dict(base, required_empty_share=0.05), 0),
        ("more_than_5_percent_missing", dict(base, required_empty_share=0.0501), 1),
        ("empty_dataset", dict(base, rows=0), 1),
        ("both_failures", dict(base, rows=79, required_empty_share=0.06), 2),
    ]
    evidence = []
    for name, current, expected in cases:
        warnings = check(base, current)
        assert len(warnings) == expected, (name, warnings)
        evidence.append({"case": name, "input": current, "warnings": warnings, "passed": True})
    for invalid in [dict(base, rows=-1), dict(base, required_empty_share=float("nan")),
                    dict(base, scope="different-window")]:
        try:
            check(base, invalid)
        except ValueError:
            continue
        raise AssertionError(f"Invalid snapshot accepted: {invalid}")
    # A synthetic redescription can leave 100 rows but empty every mandatory field.
    # Verify the analyzer catches the missing cells, independently of crawler DropItem.
    sample = {"business_key": "", "quote": "", "author": "", "author_url": "", "born_date": "1800-01-01",
              "born_location": "", "biography": "", "source_url": "", "list_page": 1,
              "collected_at": "", "tags_json": "[]"}
    synthetic = summarize([sample])
    assert synthetic["required_empty_share"] == 0.8
    evidence.append({"case": "missing_fields_analyzed", "share": synthetic["required_empty_share"], "passed": True})
    target = Path(__file__).parent / "smoke_demonstration.json"
    target.write_text(json.dumps({"synthetic_cases_only": True, "cases": evidence,
                                 "invalid_snapshot_checks": 3}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Smoke thresholds and invalid inputs: {len(cases) + 4} checks passed")


if __name__ == "__main__":
    main()
