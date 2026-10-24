"""Catálogo persistente de tiendas españolas y análisis de cobertura con conteos reales."""
import json
import re
import time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.parse import urlparse,urljoin
from concurrent.futures import ThreadPoolExecutor,as_completed
from bs4 import BeautifulSoup
from cero import http
from cero.db import connect,now
from cero.policy import allowed,host_of,canonical,known_store
from cero.retailers import STORES
from cero.listings import extract_listing
from cero.market import COUNTRY,CUSTOM_STORES

CATEGORIES={'bicycle':'Deporte','sports':'Deporte','outdoor':'Deporte','clothes':'Moda','shoes':'Moda',
 'electronics':'Tecnología','computer':'Tecnología','mobile_phone':'Tecnología','toys':'Juguetes',
 'beauty':'Belleza y salud','cosmetics':'Belleza y salud','furniture':'Hogar y cocina','houseware':'Hogar y cocina',
 'hardware':'Bricolaje','pet':'Mascotas','wine':'Alimentación','books':'Libros','jewelry':'Joyería'}


def register(c,name,url,origin,category='Otros'):
    if not url.startswith('http'):url='https://'+url
    p=urlparse(url);domain=host_of(url)
    if not allowed(url,True) or not domain or any(x in domain for x in ('google','facebook','instagram','blogspot','tripadvisor','wixsite','twitter','youtube','linktr.ee','wordpress.com')):return
    if not p.path or p.path=='/':url=canonical(url)
    c.execute('INSERT INTO stores(domain,name,url,origin,category,country) VALUES(?,?,?,?,?,?) ON CONFLICT(domain) DO NOTHING',
              (domain,str(name or domain)[:160],url,origin,category,COUNTRY))


def import_catalog(osm_path=None):
    c=connect()
    for custom in CUSTOM_STORES:register(c,custom['name'],custom['url'],'Configuración personal',custom.get('category','Otros'))
    for s in (STORES if COUNTRY=='ES' else []):
        p=urlparse(s['url']);register(c,s['name'],'https://'+p.netloc+'/','Catálogo inicial')
    if COUNTRY=='ES':
        register(c,'Amazon','https://www.amazon.es/','Catálogo inicial')
        register(c,'Cuatro Rayas','https://cuatrorayas.es/','Referencia del usuario','Alimentación')
        seed=Path(__file__).resolve().parent.parent/'catalogs'/'ES.json'
        if seed.exists():
            for store in json.loads(seed.read_text(encoding='utf8')):register(c,store['name'],store['url'],store.get('origin','Catálogo España'),store.get('category','Otros'))
    if osm_path and Path(osm_path).exists():
        data=json.loads(Path(osm_path).read_text(encoding='utf-8'))
        for item in data.get('elements',[]):
            tags=item.get('tags',{});url=tags.get('website') or tags.get('contact:website')
            if tags.get('shop') not in set(CATEGORIES)|{'department_store','supermarket','bag','gift','kitchen','watches'}:continue
            if tags.get('addr:country') and tags.get('addr:country')!='ES':continue
            if url and ';' not in url:register(c,tags.get('name') or tags.get('brand'),url,'OpenStreetMap · comercio localizado en España',CATEGORIES.get(tags.get('shop'),'Otros'))
    c.commit();n=c.execute('SELECT COUNT(*) FROM stores').fetchone()[0];c.close();return n


def analyze(store):
    start=time.monotonic();name=store['name'];url=store['url'];domain=store['domain']
    status='error';detail='';platform='';products=[];links=[]
    try:
        code,html,final=http.get(url,timeout=8)
        if code!=200 or http._blocked(code,html):status='blocked';detail=f'HTTP {code}'
        elif not allowed(final,True):status='excluded';detail='Redirección a dominio fuera de ámbito'
        else:
            s=BeautifulSoup(html,'lxml');low=html.lower()
            if 'woocommerce' in low:platform='WooCommerce'
            elif 'wp-easycart' in low:platform='WP EasyCart'
            elif 'cdn.shopify.com' in low or 'shopify.theme' in low:platform='Shopify'
            elif 'prestashop' in low:platform='PrestaShop'
            elif 'magento' in low or 'hyva' in low:platform='Magento'
            elif 'deporvillage.com' in domain:platform='Deporvillage'
            else:platform='HTML / schema.org'
            for a in s.select('a[href]'):
                href=urljoin(final,a['href'])
                text=a.get_text(' ',strip=True)
                if host_of(href)==host_of(final) and re.search(r'outlet|liquidaci[oó]n|rebajas|ofertas|sale|stock',text+' '+urlparse(href).path,re.I):
                    if allowed(href,True) and href not in links:links.append(href)
            products=extract_listing(html,final,name,'')
            # Una web de comercio local no implica que tenga venta por Internet.
            commerce=platform!='HTML / schema.org' or bool(products) or bool(re.search(r'carrito|a la cesta|comprar ahora|tienda online|compra online',s.get_text(' ',strip=True),re.I))
            if s.select_one('a[href*="mi-presupuesto"]'):
                commerce=False;products=[];platform='Presupuestos'
            status='ok' if commerce else 'website'
            detail=f'{len(products)} precios; {len(links)} secciones de ofertas' if commerce else 'Catálogo por presupuesto' if platform=='Presupuestos' else 'Web del comercio localizada; venta online sin confirmar'
            if commerce:
                for sale_url in links[:2]:
                    try:
                        sc,sh,sf=http.get(sale_url,timeout=8)
                        if sc==200:products.extend(extract_listing(sh,sf,name,''))
                    except Exception:pass
                if platform in ('WooCommerce','Shopify'):
                    from cero.hunter import catalog_job
                    products.extend(catalog_job(host_of(final),'woo' if platform=='WooCommerce' else 'shopify'))
    except Exception as e:detail=type(e).__name__
    c=connect()
    try:
        retry=(datetime.now(timezone.utc)+timedelta(hours=24 if status=='ok' else 48)).isoformat(timespec='seconds')
        c.execute('UPDATE stores SET checked_at=?,status=?,platform=?,products=?,sale_links=?,detail=?,next_check=? WHERE domain=?',
           (now(),status,platform,len(products),json.dumps(links[:8]),detail,retry,domain));c.commit()
        # Guardar precios de catálogo para reconocer caídas futuras del mismo producto.
        for d in products:
            if d.get('price') is not None and d.get('url'):c.execute('INSERT OR IGNORE INTO price_baselines VALUES(?,?,?)',(canonical(d['url']),d['price'],now()))
        c.commit()
    finally:c.close()
    return products,links,status


def analyze_catalog(limit=600,log=None,stop=None,progress=None,on_candidates=None):
    log=log or print;c=connect()
    stores=[dict(r) for r in c.execute('SELECT * FROM stores WHERE enabled=1 AND (next_check IS NULL OR next_check<=?) ORDER BY checked_at IS NOT NULL,checked_at LIMIT ?',(now(),limit))];c.close()
    log(f'Cobertura: comprobando {len(stores)} tiendas con dominio único.');candidates=[]
    if progress:progress(0,len(stores))
    from cero.hunter import candidate
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures=[pool.submit(analyze,s) for s in stores]
        for i,f in enumerate(as_completed(futures),1):
            if stop and stop():
                for x in futures:x.cancel()
                break
            try:products,links,status=f.result()
            except Exception:continue
            found=[d for d in products if candidate(d)];candidates.extend(found)
            if on_candidates and found:on_candidates(found)
            if progress:progress(i,len(stores))
            if i%25==0 or i==len(stores):log(f'Cobertura: {i}/{len(stores)} tiendas analizadas en esta pasada.')
    return candidates
