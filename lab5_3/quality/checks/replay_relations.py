"""Replay a relation feed into an existing DB and report actual versus ignored inserts."""
import json
import sys
from pathlib import Path
from scrapy.settings import Settings
from scrapy.statscollectors import MemoryStatsCollector
from quotes_crawler.tag_pipelines import StoreRelations
class Crawler: pass
c = Crawler(); c.settings = Settings({"DATABASE_PATH":sys.argv[1]}); c.stats = MemoryStatsCollector(c)
store = StoreRelations.from_crawler(c); store.open_spider()
for line in Path(sys.argv[2]).read_text(encoding="utf8").splitlines():
    store.process_item(json.loads(line))
store.close_spider()
result = {k:c.stats.get_value(k,0) for k in ("database/relations_attempted","database/relations_written","database/relations_ignored","database/total_relations")}
output = json.dumps(result, ensure_ascii=False, indent=2)
if len(sys.argv) > 3: Path(sys.argv[3]).write_text(output, encoding="utf8")
print(output)
