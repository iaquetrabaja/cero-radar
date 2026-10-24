from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI,Query,HTTPException,Request
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel,Field
from cero.db import connect,meta,query_deals,unpack,now,set_setting
from cero.scanner import start,status,stop,boot,shutdown,schedule_config
from cero.policy import allowed,canonical,public_url
from cero.images import IMAGES

STATIC=Path(__file__).resolve().parent/'static'

@asynccontextmanager
async def lifespan(app):
    boot();yield;shutdown()

app=FastAPI(title='CERO · Radar de chollos',lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','testserver','[::1]'])
app.mount('/static',StaticFiles(directory=STATIC),name='static')
app.mount('/media',StaticFiles(directory=IMAGES),name='media')

@app.middleware('http')
async def local_changes(request:Request,call_next):
    origin=request.headers.get('origin')
    if request.method not in ('GET','HEAD','OPTIONS') and origin:
        parsed=urlparse(origin)
        try:port=parsed.port or (443 if parsed.scheme=='https' else 80)
        except ValueError:return JSONResponse({'detail':'Origen no permitido'},status_code=403)
        if (parsed.hostname,port) not in {('localhost',8765),('127.0.0.1',8765),('::1',8765),('testserver',80)}:
            return JSONResponse({'detail':'Origen no permitido'},status_code=403)
    return await call_next(request)

class ScanIn(BaseModel):profile:str='normal'
class WatchIn(BaseModel):url:str=Field(min_length=8,max_length=1600)
class FavoriteIn(BaseModel):favorite:bool
class StoreIn(BaseModel):
    name:str=Field(min_length=2,max_length=160)
    url:str=Field(min_length=8,max_length=1600)
    category:str=Field(default='Otros',max_length=80)
class ScheduleIn(BaseModel):
    enabled:bool=True
    continuous:bool=True
    cycle_pause_seconds:int=Field(default=60,ge=30,le=3600)
    watch_minutes:int=Field(default=15,ge=5,le=1440)
    discovery_minutes:int=Field(default=60,ge=15,le=1440)
    deep_hours:int=Field(default=24,ge=6,le=168)

@app.get('/')
def home():return FileResponse(STATIC/'index.html')

@app.get('/api/deals')
def deals(country:str='',store:str='',category:str='',subcategory:str='',product_type:str='',q:str='',min_discount:float=Query(0,ge=0,le=100),
 min_score:float=Query(0,ge=0,le=100),free_only:int=0,hide_samples:int=1,known_only:int=0,stock_only:int=0,favorites:int=0,
 status:str='radar',score_source:str='',max_price:float|None=Query(None,ge=0),sort:str='score',limit:int=Query(200,ge=1,le=500)):
    c=connect()
    try:return {'deals':query_deals(c,**{k:v for k,v in locals().copy().items() if k!='c'})}
    finally:c.close()

@app.get('/api/meta')
def meta_view():
    c=connect()
    try:return meta(c)
    finally:c.close()

@app.get('/api/status')
def status_view():return status()

@app.post('/api/scan')
def scan(body:ScanIn):
    if body.profile not in ('normal','deep','watch'):raise HTTPException(422,'Perfil no válido')
    return {'started':start(body.profile),'profile':body.profile}

@app.post('/api/stop')
def stop_view():return {'stopping':stop()}

@app.get('/api/sources')
def sources():
    c=connect()
    try:return {'sources':[dict(r) for r in c.execute('SELECT * FROM source_health ORDER BY kind,status,name')],
       'queries':[dict(r) for r in c.execute('SELECT * FROM query_history ORDER BY id DESC LIMIT 30')]}
    finally:c.close()

@app.get('/api/runs')
def runs():
    c=connect()
    try:return {'runs':[dict(r) for r in c.execute('SELECT * FROM runs ORDER BY id DESC LIMIT 20')]}
    finally:c.close()

@app.get('/api/stores')
def stores(q:str='',state:str='',limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0)):
    c=connect();clauses=['enabled=1'];values=[]
    try:
        if q:clauses.append('(name LIKE ? OR domain LIKE ?)');values.extend(['%'+q+'%']*2)
        if state:clauses.append('status=?');values.append(state)
        where=' AND '.join(clauses)
        count=c.execute('SELECT COUNT(*) FROM stores WHERE '+where,values).fetchone()[0]
        rows=[dict(r) for r in c.execute('SELECT * FROM stores WHERE '+where+' ORDER BY checked_at DESC,name LIMIT ? OFFSET ?',values+[limit,offset])]
        return {'stores':rows,'total':count,'offset':offset,'limit':limit}
    finally:c.close()

@app.get('/api/restocks')
def restocks():
    c=connect()
    try:
        return {'restocks':[dict(r) for r in c.execute("SELECT r.*,d.title,d.store,d.price,d.availability,d.status,d.image,d.image_status FROM restocks r JOIN deals d ON d.id=r.deal_id WHERE r.active=1 AND d.image_status='verified' AND d.page_status='ok' ORDER BY r.next_check")]}
    finally:c.close()

@app.post('/api/stores')
def add_store(body:StoreIn):
    if not allowed(body.url,True) or not public_url(body.url):raise HTTPException(422,'Dominio no permitido para este país')
    from cero.registry import register
    c=connect()
    try:
        register(c,body.name,body.url,'Añadida por el usuario',body.category);c.commit()
        return {'saved':True}
    finally:c.close()

@app.get('/api/deals/{key}')
def detail(key:str):
    c=connect()
    try:
        row=c.execute('SELECT * FROM deals WHERE id=?',(key,)).fetchone()
        if not row:raise HTTPException(404,'Oferta no encontrada')
        return {'deal':unpack(row),'history':[dict(r) for r in c.execute('SELECT price,status,checked_at FROM observations WHERE deal_id=? ORDER BY id DESC LIMIT 60',(key,))]}
    finally:c.close()

@app.post('/api/deals/{key}/favorite')
def favorite(key:str,body:FavoriteIn):
    c=connect()
    try:
        row=c.execute('SELECT url,title FROM deals WHERE id=?',(key,)).fetchone()
        if not row:raise HTTPException(404,'Oferta no encontrada')
        c.execute('UPDATE deals SET favorite=? WHERE id=?',(int(body.favorite),key))
        if body.favorite:c.execute('INSERT OR IGNORE INTO watches VALUES(?,?,?)',(row['url'],row['title'],now()))
        c.commit();return {'ok':True}
    finally:c.close()

@app.post('/api/deals/{key}/recheck')
def recheck(key:str):
    c=connect()
    try:
        r=c.execute('SELECT url FROM deals WHERE id=?',(key,)).fetchone()
        if not r:raise HTTPException(404,'Oferta no encontrada')
        if not start('single',r['url']):raise HTTPException(409,'Ya hay un rastreo en curso')
        return {'started':True}
    finally:c.close()

@app.get('/api/watches')
def watches():
    c=connect()
    try:
        from cero.policy import affiliate_url
        return {'watches':[{**dict(r),'buy_url':affiliate_url(r['url'])} for r in c.execute('SELECT * FROM watches ORDER BY created_at DESC')]}
    finally:c.close()

@app.post('/api/watches')
def add_watch(body:WatchIn):
    if not allowed(body.url,True) or not public_url(body.url):raise HTTPException(422,'Usa una ficha pública de una tienda que venda en España')
    url=canonical(body.url);c=connect()
    try:c.execute('INSERT OR IGNORE INTO watches VALUES(?,?,?)',(url,'',now()));c.commit()
    finally:c.close()
    return {'saved':True,'started':start('single',url)}

@app.delete('/api/watches')
def delete_watch(url:str):
    c=connect()
    try:c.execute('DELETE FROM watches WHERE url=?',(canonical(url),));c.commit();return {'ok':True}
    finally:c.close()

@app.get('/api/settings')
def get_settings():
    c=connect()
    try:return {'schedule':schedule_config(c)}
    finally:c.close()

@app.put('/api/settings')
def put_settings(body:ScheduleIn):
    c=connect()
    try:set_setting(c,'schedule',body.model_dump());c.commit();return {'schedule':schedule_config(c)}
    finally:c.close()
