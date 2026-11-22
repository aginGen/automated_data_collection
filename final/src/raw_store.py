from hashlib import sha256
from pathlib import Path

from .files import append_jsonl, read_json, read_jsonl, utc_now, write_json


class RawStore:
    def __init__(self, root: Path, parser_version: str, run_id: str):
        self.raw = root / "raw"
        self.state = root / "state" / "etags.json"
        self.parser_version = parser_version
        self.run_id = run_id
        self.validators = read_json(self.state, {})
        self.latest = {}
        self.fx_snapshots = []
        for source in ("books", "fx"):
            for envelope in read_jsonl(self.raw / f"{source}.jsonl"):
                self.latest[envelope["_source_url"]] = envelope
                if source == "fx":
                    self.fx_snapshots.append(envelope)

    def conditional(self, url):
        envelope = self.latest.get(url)
        if envelope is None:
            return {}, 0
        cached = self.validators.get(url)
        if cached is None or cached["sha256"] != envelope["_sha256"]:
            cached = envelope["_headers"]
        headers = {}
        for saved, sent in (("etag", "If-None-Match"), ("last_modified", "If-Modified-Since")):
            if cached.get(saved):
                headers[sent] = cached[saved]
        return headers, cached.get("wire_bytes", 0)

    def put(self, source, url, response):
        old = self.latest.get(url)
        if response.status == 304:
            if old is None:
                raise ValueError("Получен HTTP 304 без сохранённого тела")
            return old
        digest = sha256(response.body.encode("utf-8")).hexdigest()
        metadata = {
            "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified"),
            "content_type": response.headers.get("Content-Type"),
            "wire_bytes": response.wire_bytes,
        }
        if old is None or old["_sha256"] != digest:
            old = {
                "_source": source,
                "_source_url": url,
                "_collected_at": utc_now(),
                "_run_id": self.run_id,
                "_parser_version": self.parser_version,
                "_status": response.status,
                "_sha256": digest,
                "_headers": metadata,
                "payload": response.body,
            }
            append_jsonl(self.raw / f"{source}.jsonl", old, sync=True)
            self.latest[url] = old
            if source == "fx":
                self.fx_snapshots.append(old)
        self.validators[url] = {**metadata, "sha256": digest}
        write_json(self.state, self.validators)
        return old

    def raw_counts(self):
        return {source: sum(1 for _ in read_jsonl(self.raw / f"{source}.jsonl")) for source in ("books", "fx")}
