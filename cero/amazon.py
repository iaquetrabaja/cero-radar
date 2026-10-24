"""Amazon España: precio y referencia ligados al mismo ASIN, nunca a cuotas o recambios."""
import re
import threading
from datetime import datetime,timedelta,timezone
from concurrent.futures import ThreadPoolExecutor,as_completed
from urllib.parse import urlencode
from bs4 import BeautifulSoup
from cero import http
from cero.db import connect,setting,set_setting,now
from cero.money import parse_amount,discount_pct,guess_type,is_sample,is_digital
from cero.hunter import health
from cero.policy import canonical
from cero.market import PROFILE

QUERIES=['cecotec','robot aspirador','bicicleta eléctrica','patinete eléctrico','maillot ciclismo','abrigo hombre',
 'zapatillas deporte','cafetera','secador pelo','auriculares','camiseta algodón','sudadera','maleta',
 'taladro','freidora aire','silla escritorio','mochila','chaqueta mujer','monitor','aspirador sin cable',
 'cámara vigilancia','batidora','teclado','herramientas jardín','pantalón hombre','chaqueta ciclismo',
 'colchón','nevera','bicicleta estática','tostadora','sandalias','pala pádel']

BRANDS=['Tommy Hilfiger','Calvin Klein','Skechers','Reebok','Jack & Jones',"Levi's",'Puma',
 'adidas','Only','Desigual','Helly Hansen','Tom Tailor','Superdry','Pepe Jeans','Columbia',
 'Under Armour','CMP','New Balance','Urban Classics','Cecotec','Bosch','Philips','Rowenta',
 'Energy Sistem','Tefal','Garmin','Fiskars','Samsonite','ASICS','Geox','Crocs','Merrell']
CATEGORIES=['fashion','electronics','kitchen','sporting','diy','garden','computers',
 'beauty','automotive','baby','toys','luggage']


def search_jobs(state,deep=False):
    """Tres recorridos independientes; cada fuente vuelve por otra página y umbral."""
    state={**state,'pages':dict(state.get('pages',{}))};jobs=[]
    for lane,values in [('query',QUERIES),('brand',BRANDS),('category',CATEGORIES)]:
        cursor=int(state.get(lane,0));count=12 if deep else 4
        for offset in range(count):
            value=values[(cursor+offset)%len(values)];key=lane+':'+value
            visit=int(state['pages'].get(key,0));page=visit%4+1
            # 80- incluye también el 100%; alternamos con 90- al volver a una fuente.
            threshold=90 if (visit//4)%2 else 80
            params={'i':value} if lane=='category' else {'k':value}
            params.update({'rh':f'p_8:{threshold}-','page':page})
            label=f'{value} · {threshold}%+ · pág. {page}'
            jobs.append((label,'https://www.'+PROFILE['amazon_domain']+'/s?'+urlencode(params)))
            state['pages'][key]=visit+1
        state[lane]=(cursor+count)%len(values)
    return jobs,state


def parse_results(html,query):
    soup=BeautifulSoup(html,'lxml');rows=[]
    for card in soup.select('[data-component-type="s-search-result"][data-asin]'):
        asin=card.get('data-asin','')
        if not re.fullmatch(r'[A-Z0-9]{10}',asin):continue
        title=card.select_one('h2');el=card.select_one('.a-price:not(.a-text-price) .a-offscreen')
        if not title or not el:continue
        image=card.select_one('img.s-image')
        names=[h.get_text(' ',strip=True) for h in card.select('h2')]
        if image:names.append(image.get('alt',''))
        name=max(names,key=len);price=parse_amount(el.get_text(' ',strip=True))
        if price is None or is_sample(name) or is_digital(name):continue
        old=card.select_one('.a-price.a-text-price .a-offscreen,[data-a-strike="true"] .a-offscreen')
        ref=parse_amount(old.get_text(' ',strip=True)) if old else None
        if not ref:
            # Los diseños nuevos presentan la referencia como texto junto a su etiqueta.
            text=card.get_text(' ',strip=True)
            m=re.search(r'(?:Mediano|Precio recomendado|Recomendado|PVP|Precio anterior)\s*:\s*([\d.,]+)\s*€',text,re.I)
            if m:ref=parse_amount(m[1])
        text=card.get_text(' ',strip=True)
        badge=re.search(r'(?:ahorra(?:r)?|descuento(?: del)?)\s*:?\s*(\d{1,3})\s*%',text,re.I)
        if not badge:badge=re.search(r'(\d{1,3})\s*%\s*(?:de descuento|de ahorro)',text,re.I)
        image=card.select_one('img.s-image')
        rows.append({'title':name,'url':'https://www.'+PROFILE['amazon_domain']+'/dp/'+asin,'store':'Amazon',
          'price':price,'reference_price':ref if ref and ref>price else None,
          'discount_pct':discount_pct(price,ref),'image':image.get('src','') if image else '',
          'source':'Amazon · '+query,'product_type':guess_type(name),'query':query,
          '_amazon_badge':int(badge[1]) if badge and int(badge[1])<=100 else 0})
    return rows


def collect(profile='normal',log=None):
    if not PROFILE.get('amazon_domain'):return [],0
    log=log or (lambda s:None);c=connect()
    retry=setting(c,'amazon_retry_after','')
    if retry and retry>now():
        c.close();log('Amazon: pausa temporal tras bloqueo; se conservan los resultados y se reintentará automáticamente.');return [],0
    chosen,state=search_jobs(setting(c,'amazon_rotation',{}),profile=='deep')
    set_setting(c,'amazon_rotation',state);c.commit();c.close()
    blocked=threading.Event();attempted=[]
    def query(job):
        if blocked.is_set():return []
        import time
        q,url=job;t=time.monotonic()
        attempted.append(q)
        try:
            st,body,final=http.get(url,timeout=12)
            if st!=200 or http._blocked(st,body):
                if http._blocked(st,body):blocked.set()
                health('Amazon · '+q,'amazon',url,'blocked',time.monotonic()-t,detail=f'HTTP {st}');return []
            rows=parse_results(body,q)
            health('Amazon · '+q,'amazon',url,'ok' if rows else 'empty',time.monotonic()-t,len(rows),f'{len(rows)} ASIN con precio principal')
            return rows
        except Exception as e:
            health('Amazon · '+q,'amazon',url,'error',time.monotonic()-t,detail=type(e).__name__);return []
    rows=[]
    with ThreadPoolExecutor(max_workers=3) as p:
        for batch in p.map(query,chosen):rows.extend(batch)
    c=connect();candidates=[];explore=[];seen=set()
    try:
        if blocked.is_set():
            set_setting(c,'amazon_retry_after',(datetime.now(timezone.utc)+timedelta(minutes=20)).isoformat(timespec='seconds'))
            log('Amazon ha mostrado una verificación de acceso. Se pausa el descubrimiento 20 minutos; no se interpreta como ausencia de ofertas.')
        for d in rows:
            if d['url'] in seen:continue
            seen.add(d['url'])
            baseline=c.execute('SELECT MAX(price) FROM price_baselines WHERE url=?',(d['url'],)).fetchone()[0]
            previous=c.execute('SELECT checked_at FROM deals WHERE url=? ORDER BY checked_at DESC LIMIT 1',(d['url'],)).fetchone()
            c.execute('INSERT OR IGNORE INTO price_baselines VALUES(?,?,?)',(d['url'],d['price'],now()))
            d['_last_checked']=previous[0] if previous else ''
            # El filtro o una insignia solo abren una ficha: no acreditan su descuento.
            if d['price']==0 or (d['discount_pct'] or 0)>=80 or d['_amazon_badge']>=80 or (baseline and d['price']<=baseline*.2):
                candidates.append(d)
            elif not d['reference_price']:explore.append(d)
        candidates.sort(key=lambda d:(bool(d['_last_checked']),d['_last_checked'],-(d['discount_pct'] or 0)))
        explore.sort(key=lambda d:(bool(d['_last_checked']),d['_last_checked'],d['price']))
        # Explora fichas sin PVP en el listado; reparte entre consultas para no monopolizar.
        counts={};extra=[]
        for d in explore:
            q=d['query'];counts[q]=counts.get(q,0)+1
            if counts[q]<=2:extra.append(d)
        candidates=candidates[:72 if profile=='deep' else 36]+extra[:24 if profile=='deep' else 12]
        c.commit()
    finally:c.close()
    log(f'Amazon: {len(attempted)} búsquedas por producto, marca y categoría; {len(seen)} ASIN; {len(candidates)} fichas para verificar (incluye indicios sin PVP).')
    return candidates,len(seen)
