"""Adaptadores de catálogos de tienda. Sólo configuración pública de búsqueda del escaparate."""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor,as_completed
from bs4 import BeautifulSoup
from curl_cffi import requests
from cero import http
from cero.money import discount_pct,guess_type
from cero.policy import public_url


def deporvillage(log=None):
    log=log or (lambda s:None)
    status,html,final=http.get('https://www.deporvillage.com/outlet',timeout=12)
    if status!=200:return [],0
    raw=html.replace('\\\\\\"','"').replace('\\"','"')
    m=re.search(r'"algolia":(\{"appId".*?\}\})',raw)
    if not m:return [],0
    cfg=json.loads(m[1]);app=cfg['appId'];key=cfg['clientApiKey'];idx=cfg['indexName']['priceAsc']
    if not re.fullmatch(r'[A-Z0-9]{6,15}',app) or not re.fullmatch(r'[\w-]+',idx):return [],0
    endpoint=f'https://{app.lower()}-dsn.algolia.net/1/indexes/{idx}/query'
    headers={'X-Algolia-Application-Id':app,'X-Algolia-API-Key':key}
    if not public_url(endpoint):return [],0
    bands=[0,1,2,5,10,15,20,30,40,50,75,100,150,200,300,500,1000,2500,5000,15000]
    filters=[['price.price=0']]
    for low,high in zip(bands,bands[1:]):
        filters.append([f'price.price>{low}',f'price.price<={high}',f'price.pvp>={max(1,low*5)}'])
    def query(f):
        r=requests.post(endpoint,headers=headers,json={'query':'','hitsPerPage':250,'numericFilters':f},timeout=15,impersonate='chrome')
        if r.status_code!=200:return [],0
        data=r.json();return data.get('hits',[]),data.get('nbHits',0)
    allhits=[];seen=set();total=0
    with ThreadPoolExecutor(max_workers=3) as p:
        for f in as_completed([p.submit(query,x) for x in filters]):
            try:hits,count=f.result()
            except Exception:continue
            total+=count
            for h in hits:
                if h.get('objectID') not in seen:seen.add(h.get('objectID'));allhits.append(h)
    out=[]
    for hit in allhits:
        p=hit.get('price') or {};price=p.get('price');ref=p.get('pvp');stock=(hit.get('defaultVariant') or {}).get('stockLabel')
        if price is None:continue
        pct=discount_pct(price,ref)
        if price!=0 and (pct or 0)<80:continue
        title=hit.get('title') or BeautifulSoup(hit.get('_highlightResult',{}).get('title',{}).get('value',''),'lxml').get_text()
        if not title:
            title=hit.get('url','').rsplit('/',1)[-1].replace('-',' ').capitalize()
        # Los ceros sin stock se conservan como evidencia, nunca como hallazgos activos.
        d={'title':title,'url':hit.get('url',''),'store':'Deporvillage','source':'Catálogo público Deporvillage',
          'price':price,'reference_price':ref if ref and ref>price else None,'discount_pct':pct,
          'product_type':guess_type(title),'catalog_stock':stock,
          'evidence':[f'Catálogo público: {price} EUR, PVP {ref}, stock {stock}.'],
          'status':'expired' if stock=='NO_STOCK' else 'candidate'}
        out.append(d)
        if stock=='NO_STOCK':log(f'Deporvillage: cero sin stock guardado para revisión en 12 h · {title[:60]}')
    log(f'Deporvillage: {len(allhits)} productos examinados por bandas de precio; {len(out)} candidatos con al menos 80%.')
    return out,len(allhits)
