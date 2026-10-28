from contextlib import closing
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.clean import clean_rows
from src.contract import quote_key
from db.load import load
import sqlite3
from src.quality import quality, require_mart
import src.rebuild as rebuild

ROOT=Path(__file__).resolve().parents[1]

class Regression(unittest.TestCase):
    def setUp(self):
        self.raw=json.loads((ROOT/'raw/api_quotes.jsonl').read_text(encoding='utf8').splitlines()[0])

    def test_fresh_invalid_duplicate_does_not_replace_old_valid(self):
        old=copy.deepcopy(self.raw)
        bad=copy.deepcopy(old); bad['tags_raw']=['not a valid tag!']; bad['_collected_at']='2026-10-26T00:00:00+00:00'
        duplicates=[]
        result,rejects,protocol=clean_rows([old,bad],duplicates)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['tags'],[])
        self.assertEqual(duplicates[0]['reason'],'invalid_duplicate')
        self.assertTrue(any(x['field']=='tags' for x in rejects))
        self.assertEqual([x['before']-x['after'] for x in protocol],[x['removed'] for x in protocol])

    def test_bootstrap_and_real_previous_volume(self):
        rows,rej,_=clean_rows([self.raw])
        metric=lambda q: next(x for x in q['metrics'] if x['metric']=='volume_change')
        self.assertIsNone(metric(quality([self.raw],rows,rej))['value'])
        self.assertEqual(metric(quality([self.raw],rows,rej,2))['value'],0.5)

    def test_prefix_and_new_file(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'raw').mkdir(); (root/'clean').mkdir()
            a=root/'raw/a.jsonl'; a.write_bytes(b'{}\n')
            (root/'raw/manifest.json').write_text('{}',encoding='utf8')
            (root/'clean/raw_prefix_manifest.json').write_text(json.dumps({'a.jsonl':{'bytes':3,'sha256':hashlib.sha256(b'{}\n').hexdigest()}}))
            (root/'raw/new.jsonl').write_bytes(b'{}\n')
            with patch.object(rebuild,'ROOT',root):
                self.assertIn('new.jsonl',rebuild.verify_raw())
                a.write_bytes(b'{}\n{}\n'); rebuild.verify_raw()
                a.write_bytes(b'[]\n')
                with self.assertRaises(RuntimeError): rebuild.verify_raw()

    def test_business_key_source_namespace_and_leading_zero(self):
        self.assertNotEqual(quote_key('a','001'),quote_key('a','1'))
        self.assertNotEqual(quote_key('a','001'),quote_key('b','001'))

    def test_same_source_id_text_change_is_update_with_history(self):
        old=copy.deepcopy(self.raw)
        newer=copy.deepcopy(old); newer['text_raw']+='!'; newer['_collected_at']='2026-10-26T00:00:00+00:00'
        first=clean_rows([old])[0]; second=clean_rows([old,newer])[0]
        self.assertEqual(len(second),1)
        self.assertEqual(first[0]['business_key'],second[0]['business_key'])
        self.assertEqual(second[0]['text'],newer['text_raw'])
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'test.db'
            load(first,[],db); result=load(second,[],db)
            self.assertEqual((result['rows'],result['updated'],result['history']),(1,1,2))
            with closing(sqlite3.connect(db)) as conn, conn:
                self.assertEqual(conn.execute('SELECT text FROM quotes').fetchone()[0],newer['text_raw'])

    def test_full_snapshot_switches_near_winner_and_reactivates(self):
        old=copy.deepcopy(self.raw); old['tags_raw']=['test-tag']; new=copy.deepcopy(old)
        new['source_id_raw']='999991'; new['text_raw']+='!'; new['_collected_at']='2026-10-26T00:00:00+00:00'
        first=clean_rows([old])[0]; second=clean_rows([old,new])[0]
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'test.db'; load(first,[],db); switched=load(second,[],db)
            self.assertEqual((switched['rows'],switched['inactive'],switched['history']),(1,1,2))
            with closing(sqlite3.connect(db)) as conn:
                before=dict(conn.execute('SELECT business_key,updated_at FROM quotes'))
                self.assertEqual(conn.execute('SELECT sum(quotes) FROM quotes_by_source').fetchone()[0],1)
                self.assertEqual(conn.execute('SELECT sum(quotes) FROM quotes_by_author').fetchone()[0],1)
                self.assertEqual(conn.execute('SELECT sum(quotes) FROM popular_tags').fetchone()[0],1)
                self.assertEqual(conn.execute('SELECT count(*) FROM quotes WHERE is_active=1').fetchone()[0],1)
            repeat=load(second,[],db)
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual(before,dict(conn.execute('SELECT business_key,updated_at FROM quotes')))
            self.assertEqual((repeat['updated'],repeat['deactivated'],repeat['unchanged']),(0,0,1))
            restored=load(first,[],db)
            self.assertEqual((restored['rows'],restored['inactive'],restored['updated']),(1,1,1))
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual(conn.execute('SELECT business_key FROM quotes WHERE is_active=1').fetchone()[0],first[0]['business_key'])

    def test_near_duplicates_different_keys(self):
        a=copy.deepcopy(self.raw); b=copy.deepcopy(a)
        b['source_id_raw']='999999'; b['text_raw']+='!'; b['_collected_at']='2026-10-26T00:00:00+00:00'
        dup=[]; rows,_,_=clean_rows([a,b],dup)
        self.assertEqual(len(rows),1); self.assertEqual(rows[0]['source_record_id'],'999999')
        self.assertEqual(dup[0]['reason'],'near_duplicate')

    def test_malformed_tags_are_rejected_and_nullable_tags_allowed(self):
        for tags in (None,'null'):
            row=copy.deepcopy(self.raw); row['tags_raw']=tags
            clean,rejects,_=clean_rows([row]); self.assertEqual(len(clean),1); self.assertEqual(clean[0]['tags'],[])
        for tags in ({'x':1},'[1]',42):
            row=copy.deepcopy(self.raw); row['tags_raw']=tags
            clean,rejects,_=clean_rows([row]); self.assertEqual(clean,[]); self.assertEqual(rejects[0]['field'],'tags_raw')

    def test_malformed_url_rejected(self):
        row=copy.deepcopy(self.raw); row['_source_url']='https://['
        clean,rejects,_=clean_rows([row]); self.assertEqual(clean,[]); self.assertEqual(rejects[0]['field'],'_source_url')

    def test_primary_keys_not_nullable(self):
        with closing(sqlite3.connect(':memory:')) as conn, conn:
            conn.executescript((ROOT/'db/schema.sql').read_text(encoding='utf8'))
            self.assertEqual(dict((row[1],row[3]) for row in conn.execute('PRAGMA table_info(quotes)'))['business_key'],1)
            self.assertEqual(dict((row[1],row[3]) for row in conn.execute('PRAGMA table_info(authors)'))['author_key'],1)
            with self.assertRaises(sqlite3.IntegrityError): conn.execute("INSERT INTO authors VALUES(NULL,'Valid name',NULL)")

    def test_red_gate(self):
        with self.assertRaisesRegex(RuntimeError,'broken'):
            require_mart({'metrics':[{'metric':'broken','status':'red'}]})

if __name__=='__main__': unittest.main()
