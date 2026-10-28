"""Проверка БД, JSONL, ключей и трёх карточек после итогового сбора."""
import hashlib
import json
import sqlite3
from pathlib import Path
rows = sqlite3.connect("data/crawl.db").execute("SELECT business_key, quote, author, tags_json, born_date, born_location, biography, list_page FROM quotes").fetchall()
assert len(rows) == 100, len(rows)
assert set(r[7] for r in rows) == set(range(1, 11))
for key, quote, author, tags, date, place, bio, page in rows:
    assert key == hashlib.sha256((author.lower() + "\n" + quote).encode("utf-8")).hexdigest()
    assert isinstance(json.loads(tags), list) and date and place and bio
examples = {"Albert Einstein": "1879-03-14", "J.K. Rowling": "1965-07-31", "Jane Austen": "1775-12-16"}
for name, expected in examples.items():
    matches = [r for r in rows if r[2] == name]
    assert matches and all(r[4] == expected for r in matches), name
lines = [json.loads(line) for line in Path("data/items_quotes.jsonl").read_text(encoding="utf-8").splitlines()]
assert len(lines) == 100 and {x["business_key"] for x in lines} == {r[0] for r in rows}
print("OK: 100 уникальных записей, 10 страниц, JSONL=SQLite, 3 карточки, ключи и поля проверены")

con = sqlite3.connect("data/crawl.db")
relations = set(con.execute("SELECT business_key,source_tag FROM quote_tags"))
expected = {(key, tag) for key, _, _, tags, _, _, _, _ in rows for tag in json.loads(tags)}
assert len(relations) == 190 and relations <= expected and len(expected) == 232
tag_feed = [json.loads(line) for line in Path("data/items_tags.jsonl").read_text(encoding="utf-8").splitlines()]
assert {(r["business_key"], r["source_tag"]) for r in tag_feed} == relations
print("OK: 190 реальных связей из 232, теги совпадают с исходными цитатами и JSONL")
