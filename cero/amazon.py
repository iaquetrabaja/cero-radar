"""Amazon España: precio y referencia ligados al mismo ASIN, nunca a cuotas o recambios."""
import re
from concurrent.futures import ThreadPoolExecutor,as_completed
from urllib.parse import quote_plus
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
            m=re.search(r'(?:Mediano|Precio recomendado|PVP|Precio anterior)\s*:\s*([\d.,]+)\s*€',text,re.I)
            if m:ref=parse_amount(m[1])
        image=card.select_one('img.s-image')
        rows.append({'title':name,'url':'https://www.'+PROFILE['amazon_domain']+'/dp/'+asin,'store':'Amazon',
          'price':price,'reference_price':ref if ref and ref>price else None,
          'discount_pct':discount_pct(price,ref),'image':image.get('src','') if image else '',
          'source':'Amazon · búsqueda por categoría','product_type':guess_type(name),'query':query})
    return rows


def collect(profile='normal',log=None):
    if not PROFILE.get('amazon_domain'):return [],0
    log=log or (lambda s:None);c=connect();cursor=setting(c,'amazon_cursor',0)
    n=16 if profile=='deep' else 6
    chosen=[QUERIES[(cursor+i)%len(QUERIES)] for i in range(n)]
    set_setting(c,'amazon_cursor',(cursor+n)%len(QUERIES));c.commit();c.close()
    def query(q):
        import time
        t=time.monotonic();url='https://www.'+PROFILE['amazon_domain']+'/s?k='+quote_plus(q)+'&pct-off=80-99'
        try:
            st,body,final=http.get(url,timeout=12)
            if st!=200 or http._blocked(st,body):
                health('Amazon · '+q,'amazon',url,'blocked',time.monotonic()-t,detail=f'HTTP {st}');return []
            rows=parse_results(body,q)
            health('Amazon · '+q,'amazon',url,'ok' if rows else 'empty',time.monotonic()-t,len(rows),f'{len(rows)} ASIN con precio principal')
            return rows
        except Exception as e:
            health('Amazon · '+q,'amazon',url,'error',time.monotonic()-t,detail=type(e).__name__);return []
    rows=[]
    with ThreadPoolExecutor(max_workers=3) as p:
        for batch in p.map(query,chosen):rows.extend(batch)
    c=connect();candidates=[];seen=set()
    try:
        for d in rows:
            c.execute('INSERT OR IGNORE INTO price_baselines VALUES(?,?,?)',(canonical(d['url']),d['price'],now()))
            if d['url'] in seen:continue
            seen.add(d['url'])
            # pct-off sirve para descubrir, nunca como prueba de descuento.
            if d['price']==0 or (d['discount_pct'] or 0)>=80:candidates.append(d)
        c.commit()
    finally:c.close()
    log(f'Amazon España: {len(chosen)} búsquedas, {len(seen)} ASIN con precio, {len(candidates)} candidatos con referencia >=80%.')
    return candidates,len(seen)
