PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS authors(
 author_key TEXT PRIMARY KEY NOT NULL CHECK(length(author_key)=24),
 name TEXT NOT NULL CHECK(length(trim(name))>=2),
 birth_year INTEGER CHECK(birth_year IS NULL OR birth_year BETWEEN 0 AND 2100)
);
CREATE TABLE IF NOT EXISTS quotes(
 business_key TEXT PRIMARY KEY NOT NULL CHECK(length(business_key)=64),
 text TEXT NOT NULL CHECK(length(text) BETWEEN 8 AND 2000),
 author_key TEXT NOT NULL REFERENCES authors(author_key),
 source TEXT NOT NULL CHECK(source IN ('quotes_html','dummyjson_api')),
 source_url TEXT NOT NULL,
 parser_version TEXT NOT NULL,
 source_record_id TEXT NOT NULL,
 collected_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 text_length INTEGER NOT NULL CHECK(text_length BETWEEN 8 AND 2000),
 tags_json TEXT NOT NULL,
 payload_hash TEXT NOT NULL,
 is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
 CHECK(text_length=length(text)),
 UNIQUE(source,source_record_id)
);
CREATE TABLE IF NOT EXISTS quote_tags(
 business_key TEXT NOT NULL REFERENCES quotes(business_key),
 tag TEXT NOT NULL CHECK(length(tag)>0),
 PRIMARY KEY(business_key,tag)
);
CREATE TABLE IF NOT EXISTS rejects(
 reject_id TEXT PRIMARY KEY,payload TEXT NOT NULL,field TEXT NOT NULL,
 reason TEXT NOT NULL,stage INTEGER NOT NULL CHECK(stage BETWEEN 1 AND 6)
);
CREATE TABLE IF NOT EXISTS quote_history(
 history_id INTEGER PRIMARY KEY AUTOINCREMENT,
 business_key TEXT NOT NULL REFERENCES quotes(business_key),
 observed_at TEXT NOT NULL,payload_hash TEXT NOT NULL,payload TEXT NOT NULL,
 UNIQUE(business_key,observed_at)
);
CREATE INDEX IF NOT EXISTS idx_quotes_author ON quotes(author_key);
CREATE INDEX IF NOT EXISTS idx_quotes_source ON quotes(source);
CREATE INDEX IF NOT EXISTS idx_tags_tag ON quote_tags(tag);
CREATE VIEW IF NOT EXISTS quotes_by_author AS
 SELECT a.name,count(*) AS quotes,round(avg(q.text_length),2) AS mean_length
 FROM quotes q JOIN authors a USING(author_key)
 WHERE q.is_active=1
 GROUP BY a.author_key ORDER BY quotes DESC;
CREATE VIEW IF NOT EXISTS quotes_by_source AS
 SELECT source,count(*) AS quotes,round(avg(text_length),2) AS mean_length
 FROM quotes WHERE is_active=1 GROUP BY source;
CREATE VIEW IF NOT EXISTS popular_tags AS
 SELECT t.tag,count(*) AS quotes FROM quote_tags t JOIN quotes q USING(business_key) WHERE q.is_active=1 GROUP BY t.tag ORDER BY quotes DESC;
