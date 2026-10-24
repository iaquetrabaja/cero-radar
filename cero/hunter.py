"""Descubrimiento rotativo, catálogos públicos y comprobación de fichas."""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timedelta,timezone
from urllib.parse import quote_plus,urljoin,urlparse
from bs4 import BeautifulSoup
from cero import http,engines
from cero.db import now,connect,setting,set_setting
from cero.policy import allowed,canonical,host_of,known_store
from cero.retailers import STORES
from cero.listings import extract_listing
from cero.verification import parse_product,category_of,base
from cero.money import is_sample,is_digital,discount_pct,guess_type
from cero.market import COUNTRY,PROFILE,CUSTOM_STORES

SEEDS=['https://www.mediamarkt.es/es/product/_secador-cecotec-ionicare-dryandkeratin-olive-1200w-tecnologia-nutriserum-motor-brushless-funcion-ionica-esencia-con-aroma-concentrador-verde-1605456.html',
 'https://www.amazon.es/dp/B0B6JQ4CVD','https://cuatrorayas.es/surtido-de-bombones/',
 'https://www.lozanogemologos.es/store/turmalina-rubelita',
 'https://etre-belle.es/products/dr-grandel-bolsa-premium?variant=53102394573123']
if COUNTRY!='ES':SEEDS=[]
PRIORITY=['MediaMarkt','Amazon','Deporvillage','PcComponentes','Decathlon','El Corte Inglés','Carrefour','Worten','Sprinter','Druni','Primor','Lidl','Cecotec','Fnac','Zalando','Mango','Miravia','Forum Sport']
SALE_PAGES=[('MediaMarkt · ofertas','https://www.mediamarkt.es/es/campaign/ofertas'),
 ('PcComponentes · ofertas','https://www.pccomponentes.com/ofertas-especiales'),
 ('Deporvillage · outlet','https://www.deporvillage.com/outlet'),
 ('Druni · outlet','https://www.druni.es/outlet'),('Primor · outlet','https://www.primor.eu/es_es/outlet'),
 ('Cecotec · ofertas','https://cecotec.es/es/ofertas'),
 ('Amazon · 90%','https://www.amazon.es/s?k=cecotec&rh=p_8%3A90-&s=price-asc-rank')]


def commands():
    from cero.footprints import generate
    c=connect()
    try:domains=[r['domain'] for r in c.execute("SELECT domain FROM stores WHERE enabled=1 AND status='ok' ORDER BY products DESC,name")]
    finally:c.close()
    priority=['amazon.es','deporvillage.com','mediamarkt.es','decathlon.es','pccomponentes.com','elcorteingles.es','lozanogemologos.es','origins.eu'] if COUNTRY=='ES' else [PROFILE.get('amazon_domain','')]
    return generate(priority+domains)


def health(name,kind,url,status,latency,products=0,detail=''):
    c=connect()
    try:
        old=c.execute('SELECT failures FROM source_health WHERE name=?',(name,)).fetchone()
        fails=(old[0] if old else 0)+1 if status in ('blocked','error','empty') else 0
        minutes=min(360,10*2**min(fails,5)) if fails else 0
        retry=(datetime.now(timezone.utc)+timedelta(minutes=minutes)).isoformat(timespec='seconds')
        c.execute('INSERT INTO source_health VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET kind=excluded.kind,url=excluded.url,status=excluded.status,checked_at=excluded.checked_at,latency=excluded.latency,products=excluded.products,detail=excluded.detail,failures=excluded.failures,next_retry=excluded.next_retry',
                  (name,kind,url,status,now(),round(latency,2),products,str(detail)[:240],fails,retry));c.commit()
    finally:c.close()


def check_url(url,previous=None):
    previous=previous or {}
    if not allowed(url,True):return None
    try:status,html,final=http.get(url,timeout=12)
    except Exception as exc:
        return _failed(url,previous,'blocked','Sin lectura de la ficha: '+type(exc).__name__)
    if status!=200 or http._blocked(status,html):
        d=_failed(url,previous,'expired' if status in (404,410) else 'blocked',f'HTTP {status}. No se confirma el precio actual.')
        if d and status in (404,410):d.update(page_status='not_found',availability='unknown')
        return d
    if not allowed(final,True):return _failed(url,previous,'rejected','Redirección fuera del ámbito permitido.')
    fragment=urlparse(url).fragment
    if re.fullmatch(r'/?sku/\d+',fragment,re.I) and host_of(url)==host_of(final) and urlparse(url).path==urlparse(final).path:
        final=final.split('#')[0]+'#'+fragment
    soup=BeautifulSoup(html,'lxml')
    heading=soup.select_one('h1.product_title,h1')
    product_title=heading.get_text(' ',strip=True) if heading else previous.get('title','')
    # Una plantilla React puede devolver 200 para una ficha eliminada. El catálogo
    # no demuestra existencia ni stock si falta la ficha real.
    has_product=bool(soup.select_one('h1.product_title,[itemtype$="/Product"],#productTitle,[data-testid="product-name"]'))
    error_heading=bool(heading and re.search(r'^(?:404\b|p[aá]gina no (?:existe|encontrada)|producto no (?:existe|encontrado)|page not found)',heading.get_text(' ',strip=True),re.I))
    blank_depor=host_of(final)=='deporvillage.com' and heading is None and not has_product and 'This page could not be found' in html
    if error_heading or blank_depor:
        d=_failed(url,previous,'expired','La ficha ya no existe o devuelve una página de error aunque HTTP indique 200. No es una reposición pendiente.')
        if d:d.update(page_status='not_found',availability='unknown')
        return d
    summary=soup.select_one('.summary,.product-summary')
    summary_text=summary.get_text(' ',strip=True) if summary else ''
    quote=soup.select_one('a[href*="mi-presupuesto"]')
    consult=any(re.search(r'^\s*(?:consultar|a consultar|consultar precio|cont[aá]ctanos)\s*$',str(t),re.I)
                for t in soup.find_all(string=True)) if previous.get('price')==0 else False
    if (quote and re.search(r'pedido m[ií]nimo|a consultar|presupuesto',summary_text,re.I)) or consult:
        d=base(final,product_title,previous.get('price'),'catálogo para presupuestos')
        minimum=re.search(r'Pedido M[ií]nimo\s*:\s*[^.]{1,70}',summary_text,re.I)
        d.update(status='rejected',availability='unknown',is_free=False,
                 conditions='Venta por presupuesto y personalización. El cero es un precio interno, no una oferta gratuita.',
                 evidence=['La ficha indica presupuesto o CONSULTAR en lugar de un precio de compra.',minimum[0] if minimum else 'Precio y plazo a consultar.'])
        return d
    path=urlparse(final).path.rstrip('/')
    if not path or path in ('/search','/buscar','/es_es/outlet','/outlet') or re.match(r'Búsqueda\b',product_title,re.I):
        return _failed(url,previous,'rejected','Es una portada o un listado; no es una ficha de producto. Se han separado sus precios.')
    offers=parse_product(final,html)
    if not offers:
        if previous.get('price')==0 and previous.get('catalog_stock')=='NO_STOCK':
            d=_failed(url,previous,'expired','0 EUR en catálogo público, sin stock. Se revisará cada 12 horas.')
            if d:d['availability']='out_of_stock'
            return d
        if host_of(final)=='amazon.es' and soup.select_one('#productTitle') and not soup.select_one('#add-to-cart-button'):
            return _failed(url,previous,'expired','Amazon no ofrece un precio principal comprable para esta variante en la lectura actual.')
        return _failed(url,previous,'unverified','La ficha no publica un precio principal verificable. Puede haber terminado la oferta.')
    d=next((d for d in offers if d['variant']==previous.get('variant','')),offers[0])
    d.setdefault('page_status','ok')
    from cero.freecheck import inspect
    inspect(d,soup)
    if d.get('status')=='rejected':return d
    from cero.shopifycheck import inspect as inspect_shopify
    inspect_shopify(d,soup)
    ref=d.get('reference_price') or 0
    if d.get('price',0)>0 and ref>5000 and ref>20*d['price']:
        d['status']='conditional'
        d['conditions']='Referencia de precio excepcionalmente alta: falta contraste independiente. No se publica como chollo verificado sólo por el porcentaje anunciado.'
    if previous.get('price') is not None and d['price']!=previous['price']:
        d['evidence'].append(f'Precio anterior observado: {previous["price"]} EUR.')
    d['source']=previous.get('source') or 'ficha'
    if d.get('_cart_eligible'):
        from cero.cartcheck import check_free_cart
        check_free_cart(d,soup)
    c=connect()
    try:
        ref_audit=c.execute('SELECT * FROM reference_audits WHERE url=?',(canonical(final),)).fetchone()
        if not ref_audit and d.get('gtin'):
            comparable=c.execute("SELECT url,price FROM deals WHERE gtin=? AND url!=? AND status='verified' AND checked_at>? AND price>0 ORDER BY price LIMIT 1",
                 (d['gtin'],d['url'],(datetime.now(timezone.utc)-timedelta(hours=24)).isoformat(timespec='seconds'))).fetchone()
            if comparable and d.get('reference_price') and comparable['price']<d['reference_price']*.5 and d['price']>comparable['price']*.2:
                ref_audit={'reason':'Otro vendedor del mismo GTIN publica un precio muy inferior al PVP tachado; ahorro real sin acreditar.',
                           'comparison_url':comparable['url'],'comparison_price':comparable['price']}
        if ref_audit and d.get('price',0)>0:
            d['status']='conditional';d['conditions']=ref_audit['reason']
            d['evidence'].append(f"Contraste: {ref_audit['comparison_price']} EUR en {ref_audit['comparison_url']}")
        audit=c.execute('SELECT payload,checked_at FROM audits WHERE url=?',(canonical(final),)).fetchone()
        if audit and d.get('price')==0 and (datetime.now(timezone.utc)-datetime.fromisoformat(audit['checked_at'])).total_seconds()<7200:
            proof=json.loads(audit['payload'])
            if d.get('_cart_eligible') and proof.get('item_at_zero') and proof.get('needs_shipping') is True and not proof.get('errors'):
                d['verification_level']='cart';d['status']='verified';d['delivery_status']='shipping_required';d['confidence']=95
                d['conditions']='Producto añadido por separado a una cesta anónima a 0 EUR. Es un artículo con envío; los gastos de transporte se confirman en la tienda.'
                if proof.get('displayed_total_eur') is not None:
                    d['shipping']=proof['displayed_total_eur'];d['total_price']=proof['displayed_total_eur']
                    d['conditions']=f"Producto a 0 EUR en cesta anónima. Gastos mostrados con impuestos: {proof['displayed_total_eur']:.2f} EUR. Importe orientativo: destino de entrega todavía sin seleccionar."
                    d['shipping_note']='Importe orientativo: destino todavía sin seleccionar.'
                    d['evidence'].append(f"Cesta: envío antes de impuestos {proof.get('shipping_before_tax_eur')} EUR; total mostrado {proof['displayed_total_eur']} EUR.")
                d['evidence'].extend(['Cesta anónima: este producto, una unidad, importe de línea 0 EUR.',
                   'El carrito declara que el artículo requiere envío físico.',
                   'No se facilitaron datos personales ni se tramitó el pedido.'])
                if proof.get('shipping_quote_eur') is not None:
                    d['shipping']=proof['shipping_quote_eur'];d['total_price']=round(d['price']+d['shipping'],2)
                    d['shipping_note']=proof.get('shipping_quote_note','Portes observados para un destino de prueba; pueden variar.')
                    d['conditions']='Producto a cero en cesta individual, con tarifa de entrega cotizada. '+d['shipping_note']
                    d['evidence'].append(f"Cesta: artículo 0 EUR; tarifa de envío cotizada {d['shipping']:.2f} EUR. {d['shipping_note']}")
                elif proof.get('platform')=='Shopify':
                    d.update(status='conditional',delivery_status='shipping_unconfirmed',confidence=50,
                             conditions='Precio cero observado en cesta, pero falta una tarifa de entrega válida para el destino de prueba. No se confirma la compra.')
            if d.get('availability')!='out_of_stock' and proof.get('item_at_zero') and proof.get('checkout_has_order_review') and proof.get('needs_shipping') is not True:
                d['verification_level']='checkout_preview';d['status']='conditional'
                d['delivery_status']='unconfirmed_no_shipping_required'
                d['conditions']='Total de 0 EUR comprobado en cesta y pantalla previa al pedido. La tienda no solicita envío para este artículo y oculta la compra: la entrega sigue sin confirmar.'
                d['evidence'].extend(['Cesta anónima: producto añadido a 0 EUR, sin otro artículo.',
                   'Pantalla previa al pedido: subtotal 0 EUR y total 0 EUR.',
                   'La API declara needs_shipping=false. No se tramitó ningún pedido.',
                   'Comprobación de cesta: '+audit['checked_at']])
        # Una caída se compara con el mismo URL, nunca con accesorios o productos distintos.
        if d.get('price') is not None and d['price']>0 and not d.get('reference_price'):
            old=[r[0] for r in c.execute('SELECT price FROM price_baselines WHERE url=? AND price>? AND observed_at<? ORDER BY observed_at DESC LIMIT 20',
                                        (d['url'],d['price'],(datetime.now(timezone.utc)-timedelta(hours=6)).isoformat(timespec='seconds')))]
            if old:
                import statistics
                ref=statistics.median(old)
                if d['price']<=ref*.2:
                    d['reference_price']=ref;d['reference_source']='Historial observado del mismo producto';d['discount_pct']=discount_pct(d['price'],ref)
        return d
    finally:c.close()


def _failed(url,previous,status,reason):
    if not previous.get('title'):return None
    d={k:v for k,v in previous.items() if k not in ('id','found_at','favorite')}
    d.update(url=canonical(url),status=status,checked_at=now(),conditions=reason,
       confidence=0,evidence=[reason],score_source='heuristic',score=0,reason=reason,page_status='unreadable')
    d.setdefault('store',known_store(url) or host_of(url))
    d.setdefault('category',category_of(previous.get('title','')))
    d.setdefault('product_type',guess_type(previous.get('title','')))
    return d


def listing_job(name,url,query=''):
    t=time.monotonic()
    try:
        code,html,final=http.get(url,timeout=12)
        if code!=200 or http._blocked(code,html):
            health(name,'tienda',url,'blocked',time.monotonic()-t,detail=f'HTTP {code}');return []
        rows=extract_listing(html,final,name.split(' · ')[0],query)
        useful=[d for d in rows if candidate(d)]
        health(name,'tienda',url,'ok' if rows else 'empty',time.monotonic()-t,len(rows),f'{len(useful)} posibles ofertas; {len(rows)} precios leídos')
        return useful
    except Exception as e:
        health(name,'tienda',url,'error',time.monotonic()-t,detail=type(e).__name__);return []


def candidate(d):
    title=d.get('title','');url=d.get('url','');price=d.get('price')
    if not allowed(url,True) or is_sample(title,url) or is_digital(title,url) or price is None:return False
    pct=d.get('discount_pct') or 0
    return price==0 or pct>=80


def search_job(engine,query):
    t=time.monotonic();error=''
    try:urls=getattr(engines,engine)(query)
    except Exception as e:urls=[];error=type(e).__name__
    site=re.search(r'site:([\w.-]+)',query)
    urls=[u for u in urls if allowed(u,True) and not re.search(r'billete|souvenir|search|buscar|categoria|category|/cart',u,re.I)
          and (not site or site[1]=='.es' and host_of(u).endswith('.es') or host_of(u)==site[1] or host_of(u).endswith('.'+site[1]))]
    c=connect()
    try:
        c.execute('INSERT INTO query_history(query,engine,urls,created_at,error) VALUES(?,?,?,?,?)',(query,engine,len(urls),now(),error));c.commit()
    finally:c.close()
    health('Buscador · '+engine,'buscador','', 'ok' if urls else 'empty',time.monotonic()-t,len(urls),error or f'{len(urls)} enlaces útiles en la última consulta')
    return urls


def catalog_job(host,platform='woo'):
    t=time.monotonic()
    url=f'https://{host}/wp-json/wc/store/v1/products?per_page=100&orderby=price&order=asc&min_price=0&max_price=0' if platform=='woo' else f'https://{host}/products.json?limit=250'
    name=host+' · catálogo'
    try:
        code,text,final=http.get(url,timeout=12,headers={'Accept':'application/json'})
        data=json.loads(text) if code==200 else None
        items=data if isinstance(data,list) else data.get('products',[]) if isinstance(data,dict) else []
        out=[]
        for p in items:
            if platform=='woo':
                prices=p.get('prices') or {};minor=prices.get('currency_minor_unit',2)
                price=int(prices['price'])/10**int(minor) if prices.get('price') is not None else None
                ref=int(prices['regular_price'])/10**int(minor) if prices.get('regular_price') else None
                if price is None:continue
                d={'title':p.get('name',''),'url':p.get('permalink',''),'price':price,'reference_price':ref,'discount_pct':discount_pct(price,ref),'source':'catálogo WooCommerce'}
                d['availability']='in_stock' if p.get('is_in_stock') else 'out_of_stock'
                if p.get('type')=='simple' and not p.get('is_virtual') and candidate(d) and (p.get('is_purchasable') and p.get('is_in_stock') or price==0 and not p.get('is_in_stock')):out.append(d)
            else:
                for v in p.get('variants',[]):
                    try:price=float(v['price']);ref=float(v.get('compare_at_price') or 0)
                    except (KeyError,ValueError,TypeError):continue
                    d={'title':p.get('title',''),'url':f'https://{host}/products/{p["handle"]}?variant={v["id"]}',
                       'price':price,'reference_price':ref,'discount_pct':discount_pct(price,ref),'source':'catálogo Shopify','variant':v.get('title','')}
                    d['availability']='in_stock' if v.get('available') else 'out_of_stock'
                    if candidate(d) and (v.get('available') or price==0):out.append(d)
        health(name,'catálogo',url,'ok' if items else 'empty',time.monotonic()-t,len(items),f'{len(out)} candidatos comprables en el catálogo')
        return out
    except Exception as e:
        health(name,'catálogo',url,'error',time.monotonic()-t,detail=type(e).__name__);return []


def discovery_jobs(conn,profile):
    jobs=[]
    stores=sorted(STORES if COUNTRY=='ES' else [],key=lambda s:PRIORITY.index(s['name']) if s['name'] in PRIORITY else 100)
    cursor=setting(conn,'store_cursor',0)
    chosen=stores if profile=='deep' or not stores else stores[:14]+[stores[(cursor+i)%len(stores)] for i in range(10)]
    if stores:set_setting(conn,'store_cursor',(cursor+10)%len(stores))
    for store in chosen:
        q=store['queries'][0]
        jobs.append(('listing',store['name'],store['url'].format(q=quote_plus(q)),q))
    for name,url in (SALE_PAGES if COUNTRY=='ES' else []):jobs.append(('listing',name,url,''))
    for host in (['cuatrorayas.es','caramelosvinuesa.com'] if COUNTRY=='ES' else []):
        jobs.append(('catalog',host,'woo',''))
    if COUNTRY=='ES':jobs.append(('catalog','www.laflorderute.es','shopify',''))
    allq=commands();cur=setting(conn,'query_cursor',0);n=30 if profile=='deep' else 16
    motors=('bing','google','ddg','yahoo','brave','mojeek')
    for i in range(n):
        q=allq[(cur+i)%len(allq)]
        for engine in (motors[(cur+i)%len(motors)],motors[(cur+i+1)%len(motors)]):jobs.append(('search',engine,q,''))
    set_setting(conn,'query_cursor',(cur+n)%len(allq));conn.commit()
    # Las fuentes con fallos repetidos descansan, sin bloquear las demás.
    cooldown={r['name'] for r in conn.execute('SELECT name FROM source_health WHERE next_retry>? AND failures>=2',(now(),))}
    return [j for j in jobs if not (j[0]=='listing' and j[1] in cooldown or j[0]=='search' and 'Buscador · '+j[1] in cooldown)]
