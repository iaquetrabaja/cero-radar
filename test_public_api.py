"""Contracts for the shared reader: no writes, secrets or private screenshots."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from cero import db, public_api


class PublicRadarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.database = self.root / 'cero.db'
        conn = sqlite3.connect(self.database)
        conn.executescript(db.BASE)
        for column, kind in db.EXTRA.items():
            conn.execute(f'ALTER TABLE deals ADD COLUMN {column} {kind}')
        self.photo = '/static/cache/' + 'a'*64 + '.webp'
        row = {'id':'offer','country':'ES','store':'Tienda','title':'Bolsa física','url':'https://tienda.es/producto/bolsa/',
               'price':0,'reference_price':20,'discount_pct':100,'image':self.photo,'image_status':'verified',
               'status':'verified','availability':'in_stock','free_review':'accepted','page_status':'ok','score':96,
               'checked_at':db.now(),'reason':'Bolsa individual a cero.','currency':'EUR','category':'Moda',
               'is_free':1,'is_sample':0,'sale_context':'INTERNAL-SENTINEL','ai_reason':'PRIVATE-RAW-ANALYSIS',
               'evidence':json.dumps(['INTERNAL-CONTEXT']),'score_source':'gemini-2.5-flash-lite'}
        names = ','.join(row)
        conn.execute(f'INSERT INTO deals({names}) VALUES({",".join("?" for _ in row)})',list(row.values()))
        conn.execute("INSERT INTO stores(domain,name,url,origin,country,enabled,checked_at,status) VALUES(?,?,?,?,?,?,?,?)",
                     ('tienda.es','Tienda','https://tienda.es','INTERNAL-ORIGIN','ES',1,db.now(),'ok'))
        conn.execute("INSERT INTO usage(model,input_tokens,output_tokens,est_eur,created_at) VALUES('PRIVATE-MODEL',1,1,2.345678,?)",(db.now(),))
        conn.execute("INSERT INTO settings VALUES('secret','PRIVATE-KEY')")
        conn.execute("INSERT INTO restocks VALUES(?,?,?,?,?,?)",('https://tienda.es/producto/bolsa/','offer',db.now(),db.now(),12,1))
        conn.commit();conn.close()
        self.patches = [patch.object(public_api,'DB_PATH',self.database)]
        for entry in self.patches:entry.start()
        self.client = TestClient(public_api.app)

    def tearDown(self):
        self.client.close()
        for entry in reversed(self.patches):entry.stop()
        self.tmp.cleanup()

    def test_metadata_omits_cost_keys_and_internal_data(self):
        response = self.client.get('/api/meta')
        self.assertEqual(response.status_code,200)
        data = response.json()
        self.assertTrue(data['read_only'])
        self.assertEqual(data['totals']['free_available'],1)
        for term in ['spent','budget','reserved','usage','secret','PRIVATE','2.345678','sources']:
            self.assertNotIn(term,response.text)

    def test_mutations_unavailable_and_reads_do_not_modify_database(self):
        before = self.database.read_bytes()
        for method,path in [('post','/api/scan'),('post','/api/watches'),('put','/api/settings'),
                            ('delete','/api/watches'),('post','/api/deals/offer/recheck')]:
            self.assertEqual(getattr(self.client,method)(path,json={}).status_code if method!='delete'
                             else self.client.delete(path).status_code,405)
        for path in ['/api/meta','/api/deals','/api/deals/offer','/api/restocks']:
            self.assertEqual(self.client.get(path).status_code,200)
        self.assertEqual(self.database.read_bytes(),before)
        with public_api.readonly_connection() as conn:
            with self.assertRaises(sqlite3.OperationalError):conn.execute("DELETE FROM settings")

    def test_administration_and_private_assets_are_not_registered(self):
        for path in ['/api/settings','/api/status','/api/sources','/api/runs','/api/watches',
                     '/api/history/image/spiuk','/static/index.html','/static/app.js',
                     '/static/cache/private-history.png','/docs','/openapi.json']:
            self.assertEqual(self.client.get(path).status_code,404,path)

    def test_product_allowlist_hides_private_analysis(self):
        response = self.client.get('/api/deals?free_only=1&stock_only=1')
        self.assertEqual(response.status_code,200)
        rows = response.json()['deals']
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['price'],0)
        self.assertEqual(rows[0]['score_kind'],'gemini')
        for term in ['sale_context','ai_reason','evidence','favorite','PRIVATE','INTERNAL','review_hold']:
            self.assertNotIn(term,response.text)

    def test_shared_html_and_assets_work_with_subpath(self):
        response = self.client.get('/cero/radar/')
        self.assertEqual(response.status_code,200)
        soup = BeautifulSoup(response.text,'lxml')
        self.assertEqual(soup.select_one('link[rel="stylesheet"]')['href'],'/cero/radar/static/app.css?v=public-1')
        self.assertEqual(soup.select_one('script[src]')['src'],'/cero/radar/static/public.js?v=1')
        self.assertIsNone(soup.select_one('#scan,#add-watch,#watch-dialog,#scan-panel,.sidebar-bottom'))
        for name in ['settings','sources','activity','watches','saved']:
            self.assertIsNone(soup.select_one(f'[data-view="{name}"]'))
        self.assertIn('maillots Spiuk',soup.get_text())
        self.assertIn('https://github.com/iaquetrabaja/cero-radar',response.text)
        self.assertNotIn('presupuesto',response.text.lower())
        self.assertEqual(self.client.get('/cero/radar/static/public.js').status_code,200)
        self.assertEqual(self.client.get('/cero/radar/static/app.css').status_code,200)
        self.assertEqual(self.client.get('/cero/radar/api/meta').status_code,200)

    def test_history_reuses_public_photos_and_never_receipts(self):
        catalogs = self.root/'catalogs';catalogs.mkdir()
        cache = self.root/'cache';cache.mkdir()
        origin = 'https://tienda.es/foto.jpg'
        photo_key = hashlib.sha256(origin.encode()).hexdigest()+'.webp'
        (cache/photo_key).write_bytes(b'public-product-photo')
        examples = [{'id':'bike','title':'Bicicleta','store':'Tienda','historical_price':72.9,'reference_price':849,
                     'url':'https://tienda.es/bici','image_url':origin},
                    {'id':'shirt','title':'Maillot','historical_price':0,'evidence_key':'spiuk','crop':[0,0,20,20]}]
        (catalogs/'ES-history.json').write_text(json.dumps(examples),encoding='utf-8')
        with patch.object(public_api,'ROOT',self.root),patch.object(public_api,'IMAGE_DIR',cache):
            response = self.client.get('/api/history')
            self.assertEqual(self.client.get('/static/cache/'+photo_key).status_code,200)
        self.assertEqual([item['id'] for item in response.json()['examples']],['bike'])
        self.assertNotIn('evidence',response.text)
        self.assertNotIn('crop',response.text)
        self.assertNotIn('spiuk',response.text)

    def test_missing_database_is_not_created(self):
        missing = self.root/'not-created.db'
        with patch.object(public_api,'DB_PATH',missing):
            self.assertEqual(self.client.get('/api/meta').status_code,503)
        self.assertFalse(missing.exists())

    def test_worker_keeps_wal_available_for_readonly_viewer_while_idle(self):
        from cero import api
        def writer_connection():
            conn=sqlite3.connect(self.database,check_same_thread=False)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute("INSERT OR REPLACE INTO settings VALUES('keepalive-test','true')")
            conn.commit()
            return conn
        with patch.object(api,'connect',side_effect=writer_connection),patch.object(api,'boot'),patch.object(api,'shutdown'):
            with TestClient(api.app):
                for _ in range(3):
                    self.assertTrue(Path(str(self.database)+'-shm').is_file())
                    self.assertTrue(Path(str(self.database)+'-wal').is_file())
                    self.assertEqual(self.client.get('/api/meta').status_code,200)
                self.assertTrue(Path(str(self.database)+'-shm').is_file())


if __name__=='__main__':
    unittest.main()
