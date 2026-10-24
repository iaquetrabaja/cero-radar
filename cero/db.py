import hashlib
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlparse,parse_qs
from cero.config import BUDGET_TIMEZONE
from cero.market import COUNTRY,CURRENCY,PROFILE
from cero.config import DB_PATH, GEMINI_BUDGET_EUR
from cero.policy import canonical, known_store, allowed,affiliate_url,host_of


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

BASE = '''
CREATE TABLE IF NOT EXISTS deals (id TEXT PRIMARY KEY, source TEXT, country TEXT, store TEXT, title TEXT, url TEXT,
 image TEXT, category TEXT, product_type TEXT, price REAL, reference_price REAL, currency TEXT, discount_pct REAL,
 is_free INTEGER, is_sample INTEGER, kind TEXT, score REAL, verdict TEXT, reason TEXT, found_at TEXT);
CREATE TABLE IF NOT EXISTS usage (id INTEGER PRIMARY KEY AUTOINCREMENT,model TEXT,input_tokens INTEGER,output_tokens INTEGER,est_eur REAL,created_at TEXT);
CREATE TABLE IF NOT EXISTS observations (id INTEGER PRIMARY KEY AUTOINCREMENT,deal_id TEXT,price REAL,status TEXT,checked_at TEXT,evidence TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY AUTOINCREMENT,profile TEXT,started_at TEXT,finished_at TEXT,status TEXT,checked INTEGER DEFAULT 0,found INTEGER DEFAULT 0,log TEXT);
CREATE TABLE IF NOT EXISTS source_health (name TEXT PRIMARY KEY,kind TEXT,url TEXT,status TEXT,checked_at TEXT,latency REAL,products INTEGER DEFAULT 0,detail TEXT,failures INTEGER DEFAULT 0,next_retry TEXT);
CREATE TABLE IF NOT EXISTS watches (url TEXT PRIMARY KEY,title TEXT DEFAULT '',created_at TEXT);
CREATE TABLE IF NOT EXISTS ai_cache (fingerprint TEXT PRIMARY KEY,result TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS ai_reservations (id TEXT PRIMARY KEY,eur REAL,created_at TEXT);
CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY AUTOINCREMENT,deal_id TEXT,channel TEXT DEFAULT 'telegram',payload TEXT,created_at TEXT,sent_at TEXT,UNIQUE(deal_id,channel));
CREATE TABLE IF NOT EXISTS query_history (id INTEGER PRIMARY KEY AUTOINCREMENT,query TEXT,engine TEXT,urls INTEGER,created_at TEXT,error TEXT);
CREATE TABLE IF NOT EXISTS stores (domain TEXT PRIMARY KEY,name TEXT,url TEXT,origin TEXT,category TEXT,country TEXT DEFAULT 'ES',enabled INTEGER DEFAULT 1,checked_at TEXT,status TEXT DEFAULT 'pending',platform TEXT,products INTEGER DEFAULT 0,sale_links TEXT DEFAULT '[]',detail TEXT,next_check TEXT);
CREATE TABLE IF NOT EXISTS restocks (url TEXT PRIMARY KEY,deal_id TEXT,last_checked TEXT,next_check TEXT,interval_hours INTEGER DEFAULT 12,active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS price_baselines (url TEXT,price REAL,observed_at TEXT,PRIMARY KEY(url,observed_at));
CREATE TABLE IF NOT EXISTS audits (url TEXT PRIMARY KEY,payload TEXT,checked_at TEXT);
CREATE TABLE IF NOT EXISTS reference_audits (url TEXT PRIMARY KEY,comparison_url TEXT,comparison_price REAL,reason TEXT,checked_at TEXT);
'''
EXTRA={'status':"TEXT DEFAULT 'unverified'",'availability':"TEXT DEFAULT 'unknown'",'checked_at':'TEXT',
 'variant':"TEXT DEFAULT ''",'shipping':'REAL','total_price':'REAL','conditions':"TEXT DEFAULT ''",
 'price_source':"TEXT DEFAULT ''",'reference_source':"TEXT DEFAULT ''",'score_source':"TEXT DEFAULT 'heuristic'",
 'confidence':'REAL DEFAULT 0','known_store':'INTEGER DEFAULT 0','favorite':'INTEGER DEFAULT 0','evidence':"TEXT DEFAULT '[]'",
 'verification_level':"TEXT DEFAULT 'page'",'delivery_status':"TEXT DEFAULT 'unknown'",'next_review':'TEXT',
 'image_status':"TEXT DEFAULT 'pending'",'image_source':"TEXT DEFAULT ''",'gtin':"TEXT DEFAULT ''",'sku':"TEXT DEFAULT ''",'page_status':"TEXT DEFAULT 'unknown'",'subcategory':"TEXT DEFAULT ''",
 'last_verified_at':'TEXT','best_price':'REAL','best_discount':'REAL','ai_score':'REAL','ai_reason':'TEXT','shipping_note':"TEXT DEFAULT ''",
 'sale_context':"TEXT DEFAULT ''",'free_review':"TEXT DEFAULT 'pending'",'free_review_reason':"TEXT DEFAULT ''",
 'review_hold':"TEXT DEFAULT ''"}
_migrated=set()


def connect():
    c=sqlite3.connect(DB_PATH,timeout=30,check_same_thread=False);c.row_factory=sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA busy_timeout=30000')
    if str(DB_PATH) not in _migrated:
        c.executescript(BASE)
        installed=setting(c,'installation_country')
        if installed and installed!=COUNTRY:raise ValueError('Esta base de datos pertenece a otro país. Selecciona otro CERO_DATA_DIR.')
        set_setting(c,'installation_country',COUNTRY)
        cols={r['name'] for r in c.execute('PRAGMA table_info(deals)')}
        for col,typ in EXTRA.items():
            if col not in cols:c.execute(f'ALTER TABLE deals ADD COLUMN {col} {typ}')
        # Los ceros antiguos también necesitan la nueva revisión semántica.
        c.execute("UPDATE deals SET status='conditional',score=MIN(COALESCE(score,0),40),verdict='revisar' WHERE price=0 AND status='verified' AND COALESCE(free_review,'pending')!='accepted'")
        c.execute("UPDATE deals SET last_verified_at=(SELECT MAX(o.checked_at) FROM observations o WHERE o.deal_id=deals.id AND o.status='verified'),best_price=price,best_discount=discount_pct WHERE last_verified_at IS NULL AND status!='rejected' AND EXISTS(SELECT 1 FROM observations o WHERE o.deal_id=deals.id AND o.status='verified')")
        if setting(c,'taxonomy_version',0)<3:
            from cero.taxonomy import classify
            for row in c.execute('SELECT id,title FROM deals').fetchall():
                tags=classify(row['title']);c.execute('UPDATE deals SET category=?,subcategory=?,product_type=? WHERE id=?',(*tags.values(),row['id']))
            set_setting(c,'taxonomy_version',3)
        seen=set()
        for r in c.execute('SELECT id,url,variant FROM deals ORDER BY found_at DESC').fetchall():
            key=(canonical(r['url'] or ''),r['variant'] or '')
            if key in seen:c.execute('DELETE FROM deals WHERE id=?',(r['id'],))
            else:seen.add(key)
        c.execute('CREATE INDEX IF NOT EXISTS idx_observation ON observations(deal_id,checked_at)')
        c.commit();_migrated.add(str(DB_PATH))
    return c


def deal_id(deal):
    return hashlib.sha256((canonical(deal.get('url',''))+'|'+(deal.get('variant') or '')).encode()).hexdigest()[:20]


def upsert(conn,deal):
    url=canonical(deal.get('url',''));variant=deal.get('variant') or ''
    old=conn.execute("SELECT * FROM deals WHERE url=? AND COALESCE(variant,'')=?",(url,variant)).fetchone()
    # Un ASIN de ficha ya identifica la variante. Completar su talla no crea otra oferta.
    if not old and host_of(url)==PROFILE.get('amazon_domain'):
        old=conn.execute('SELECT * FROM deals WHERE url=? ORDER BY found_at LIMIT 1',(url,)).fetchone()
    if not old and '/products/' in urlparse(url).path and parse_qs(urlparse(url).query).get('variant'):
        old=conn.execute('SELECT * FROM deals WHERE url=? ORDER BY found_at LIMIT 1',(url,)).fetchone()
    if not old:
        old=next((r for r in conn.execute("SELECT * FROM deals WHERE status='unverified'")
                  if canonical(r['url'] or '')==url and (r['variant'] or '')==variant),None)
    row=dict(old) if old else {}
    valid={'id','source','country','store','title','url','image','category','product_type','price','reference_price',
           'currency','discount_pct','is_free','is_sample','kind','score','verdict','reason','found_at'}|set(EXTRA)
    row.update({k:v for k,v in deal.items() if k in valid})
    # A reported false positive is independent evidence. A subsequent cart read
    # or optimistic AI response must not silently clear the unresolved report.
    if deal.get('_release_review_hold'):
        row['review_hold']=''
    elif old and old['review_hold']:
        row['review_hold']=old['review_hold']
    if row.get('review_hold') and row.get('status')!='rejected':
        held={'status':'conditional','free_review':'uncertain','verdict':'revisar','score_source':'review_hold','reason':row['review_hold'],
              'score':min(row.get('score') or 0,40),'conditions':row['review_hold'],
              'free_review_reason':row['review_hold']}
        row.update(held);deal.update(held,review_hold=row['review_hold'])
    from cero.taxonomy import classify
    tags=classify(row.get('title',''))
    if tags['category']!='Otros' or not row.get('category') or row.get('category')=='Otros':row.update(tags)
    row['id']=old['id'] if old else deal_id(deal);row['url']=url
    row['found_at']=old['found_at'] if old else deal.get('found_at') or now()
    row['country']=COUNTRY;row['currency']=deal.get('currency') or CURRENCY
    row['known_store']=int(bool(known_store(url)));row['is_free']=int(row.get('price')==0)
    row['is_sample']=int(bool(row.get('is_sample')));row['checked_at']=deal.get('checked_at') or now()
    if row.get('price')==0 and row.get('status')=='verified' and deal.get('free_review')!='accepted':
        row.update(status='conditional',free_review='pending',score=min(row.get('score') or 0,40),verdict='revisar')
    if row.get('status')=='verified' and (row.get('price')==0 or (row.get('discount_pct') or 0)>=80):
        row['last_verified_at']=row['checked_at']
        row['best_price']=min(v for v in [row.get('best_price'),row.get('price')] if v is not None)
        row['best_discount']=max(row.get('best_discount') or 0,row.get('discount_pct') or 0)
    delay=12*60 if row.get('price')==0 and row.get('availability')=='out_of_stock' else 15
    row['next_review']=(datetime.fromisoformat(row['checked_at'])+timedelta(minutes=delay)).isoformat(timespec='seconds')
    if isinstance(row.get('evidence'),list):row['evidence']=json.dumps(row['evidence'],ensure_ascii=False)
    cols=list(row)
    conn.execute(f"INSERT INTO deals ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)}) ON CONFLICT(id) DO UPDATE SET "+
                 ','.join(f'{k}=excluded.{k}' for k in cols if k!='id'),list(row.values()))
    conn.execute('INSERT INTO observations(deal_id,price,status,checked_at,evidence) VALUES(?,?,?,?,?)',
                 (row['id'],row.get('price'),row.get('status','unverified'),row['checked_at'],row.get('evidence','[]')))
    if row.get('page_status') in ('not_found','unavailable') or row.get('status')=='rejected':
        conn.execute('UPDATE restocks SET active=0,last_checked=? WHERE url=?',(row['checked_at'],url))
    elif row.get('price')==0 and row.get('availability')=='out_of_stock' and row.get('page_status')=='ok':
        next_check=(datetime.fromisoformat(row['checked_at'])+timedelta(hours=12)).isoformat(timespec='seconds')
        conn.execute('INSERT INTO restocks(url,deal_id,last_checked,next_check) VALUES(?,?,?,?) ON CONFLICT(url) DO UPDATE SET deal_id=excluded.deal_id,last_checked=excluded.last_checked,next_check=excluded.next_check,active=1',
                     (url,row['id'],row['checked_at'],next_check))
    elif row.get('availability') in ('in_stock','preorder'):
        conn.execute('UPDATE restocks SET active=0,last_checked=? WHERE url=?',(row['checked_at'],url))
    return row['id']


def add_usage(conn,model,input_tokens,output_tokens,est_eur):
    conn.execute('INSERT INTO usage(model,input_tokens,output_tokens,est_eur,created_at) VALUES(?,?,?,?,?)',
                 (model,input_tokens,output_tokens,est_eur,now()))


def budget_window(at=None):
    local=(at or datetime.now(timezone.utc)).astimezone(ZoneInfo(BUDGET_TIMEZONE))
    start=local.replace(hour=0,minute=0,second=0,microsecond=0)
    return start.astimezone(timezone.utc).isoformat(timespec='seconds'),(start+timedelta(days=1)).astimezone(timezone.utc).isoformat(timespec='seconds')


def spent_eur(conn):
    start,end=budget_window()
    return float(conn.execute('SELECT COALESCE(SUM(est_eur),0) FROM usage WHERE created_at>=? AND created_at<?',(start,end)).fetchone()[0])


def setting(conn,key,default=None):
    r=conn.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
    return json.loads(r[0]) if r else default


def set_setting(conn,key,value):
    conn.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,json.dumps(value)))


def cutoff():return (datetime.now(timezone.utc)-timedelta(hours=2)).isoformat(timespec='seconds')


def unpack(row):
    d=dict(row)
    d['buy_url']=affiliate_url(d.get('url') or '')
    try:d['evidence']=json.loads(d.get('evidence') or '[]')
    except (ValueError,TypeError):d['evidence']=[]
    if d.get('price')==0 and d.get('status')=='verified' and d.get('free_review')!='accepted':d['status']='conditional'
    if d.get('review_hold') and d.get('status')!='rejected':
        d.update(status='conditional',free_review='uncertain',score=min(d.get('score') or 0,40),score_source='review_hold',reason=d['review_hold'])
    if d.get('status')=='verified' and (not d.get('checked_at') or d['checked_at']<cutoff()):d['status']='stale'
    if d.get('status')=='verified' and d.get('price')!=0 and (d.get('discount_pct') or 0)<80:d['status']='ended'
    if d.get('page_status')=='not_found' and d.get('last_verified_at'):d['status']='removed'
    return d


def query_deals(conn,**f):
    clauses=['1=1'];params=[]
    if f.get('image_only',True):clauses.append("image_status='verified' AND image LIKE '/static/cache/%'")
    # Umbral editorial del radar, incluido en todos los filtros y estadísticas.
    if not f.get('include_below_threshold'):
        clauses.append('(price=0 OR COALESCE(discount_pct,0)>=80 OR (last_verified_at IS NOT NULL AND (best_price=0 OR best_discount>=80)))')
    for key in ('country','category','subcategory','product_type','status','score_source'):
        if f.get(key) and f[key]!='all':
            if key=='status' and f[key]=='radar':
                clauses.append("(status='verified' OR (last_verified_at IS NOT NULL AND status IN ('stale','blocked','unverified','expired','conditional','candidate')) OR (price=0 AND availability='out_of_stock' AND page_status='ok' AND status='expired'))")
            elif key=='status' and f[key]=='stale':
                clauses.append("(status='stale' OR (status='verified' AND checked_at < ?))");params.append(cutoff())
            else:
                clauses.append(key+'=?');params.append(f[key])
                if key=='status' and f[key]=='verified':
                    clauses.extend(['checked_at >= ?','(price=0 OR discount_pct>=80)',"COALESCE(review_hold,'')=''"]);params.append(cutoff())
    for key in ('store','q'):
        if f.get(key):
            cols=['store'] if key=='store' else ['title','store','product_type','variant']
            clauses.append('('+' OR '.join(col+' LIKE ?' for col in cols)+')');params.extend(['%'+f[key]+'%']*len(cols))
    for key in ('min_discount','min_score'):
        if f.get(key):clauses.append(('discount_pct' if key=='min_discount' else 'score')+'>=?');params.append(f[key])
    if f.get('max_price') is not None:clauses.append('price<=?');params.append(f['max_price'])
    for key,col in [('free_only','is_free'),('known_only','known_store'),('favorites','favorite')]:
        if f.get(key):clauses.append(col+'=1')
    if f.get('hide_samples',True):clauses.append('COALESCE(is_sample,0)=0')
    if f.get('stock_only'):clauses.append("availability IN ('in_stock','preorder')")
    order={'score':'score DESC','discount':'discount_pct DESC','price':'price ASC','new':'found_at DESC','checked':'checked_at DESC'}.get(f.get('sort'),'score DESC')
    rows=conn.execute(f"SELECT * FROM deals WHERE {' AND '.join(clauses)} ORDER BY {order},checked_at DESC LIMIT ?",params+[min(500,max(1,int(f.get('limit') or 200)))]).fetchall()
    return [unpack(r) for r in rows if allowed(r['url'],r['country']==COUNTRY)]


def meta(conn):
    rows=query_deals(conn,limit=500);radar=query_deals(conn,status='radar',limit=500);active=[d for d in radar if d['status']=='verified']
    def col(name):
        values={}
        for d in rows:
            if d.get(name):values[d[name]]=values.get(d[name],0)+1
        return [{'value':v,'count':n} for v,n in sorted(values.items())]
    coverage=dict(conn.execute("SELECT COUNT(*) monitored,SUM(CASE WHEN checked_at IS NOT NULL THEN 1 ELSE 0 END) analyzed,SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) online,SUM(CASE WHEN status='blocked' THEN 1 ELSE 0 END) blocked FROM stores WHERE enabled=1").fetchone())
    restocks=conn.execute("SELECT COUNT(*) FROM restocks r JOIN deals d ON d.id=r.deal_id WHERE r.active=1 AND d.image_status='verified' AND d.page_status='ok'").fetchone()[0]
    cart_zeros=conn.execute("SELECT COUNT(*) FROM deals WHERE price=0 AND verification_level='checkout_preview' AND status='conditional' AND image_status='verified'").fetchone()[0]
    missing_images=conn.execute("SELECT COUNT(*) FROM deals WHERE status!='rejected' AND COALESCE(image_status,'pending')!='verified' AND (price=0 OR discount_pct>=80)").fetchone()[0]
    return {'market':{k:PROFILE[k] for k in ('country','name','currency','language')},'coverage':coverage,'restocks':restocks,'cart_zeros':cart_zeros,'missing_images':missing_images,'countries':[{'value':COUNTRY,'count':len(rows)}],'stores':col('store'),'categories':col('category'),'subcategories':col('subcategory'),'types':col('product_type'),'sources':col('source'),
     'totals':{'deals':len(radar),'available':len(active),'free':sum(d['price']==0 for d in radar),'free_available':sum(d['price']==0 for d in active),'extreme':sum((d['discount_pct'] or 0)>=90 for d in radar),
     'stores':len({d['store'] for d in active}),'pending':sum(d['status'] in ('unverified','candidate','blocked','stale','conditional') for d in rows)},
     'spent_eur':round(spent_eur(conn),6),'lifetime_spent_eur':conn.execute('SELECT COALESCE(SUM(est_eur),0) FROM usage').fetchone()[0],
     'budget_eur':GEMINI_BUDGET_EUR,'budget_period':'daily','budget_timezone':BUDGET_TIMEZONE,'budget_resets_at':budget_window()[1],
     'reserved_eur':conn.execute('SELECT COALESCE(SUM(eur),0) FROM ai_reservations').fetchone()[0]}
