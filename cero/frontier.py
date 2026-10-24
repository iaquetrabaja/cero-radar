"""Descubrimiento incremental de rebajas en catálogos y productos nuevos de sitemaps."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timedelta,timezone
import json
import re
from urllib.parse import urlparse,urljoin
import xml.etree.ElementTree as ET
from cero import http
from cero.db import connect,setting,set_setting,now
from cero.hunter import health,candidate
from cero.money import discount_pct
from cero.policy import canonical,allowed,host_of
from bs4 import BeautifulSoup
from cero.money import is_sample,is_digital
from cero.market import CURRENCY


def shopify_price_floor(store):
    """Find zero variants beyond the first page of the ordinary product feed."""
    root=store['url'].rstrip('/');host=store['domain'];found=[];read=0
    code,body,_=http.get(root+'/collections/all?sort_by=price-ascending',timeout=9)
    if code!=200 or http._blocked(code,body):return [],0
    handles=[]
    for a in BeautifulSoup(body,'lxml').select('a[href*="/products/"]'):
        match=re.search(r'/products/([^/?#]+)',a['href'])
        if match and match[1] not in handles:handles.append(match[1])
    for handle in handles[:7]:
        if is_sample(handle) or is_digital(handle):continue
        code,body,_=http.get(root+'/products/'+handle+'.js',timeout=8)
        if code!=200:continue
        product=json.loads(body);read+=1
        # The single-product .js endpoint uses cents; products.json uses euros.
        variants=[{**v,'price':float(v['price'])/100,
                   'compare_at_price':float(v.get('compare_at_price') or 0)/100}
                  for v in product.get('variants',[]) if v.get('price') is not None]
        images=[{'src':urljoin(root,img)} for img in product.get('images',[]) if isinstance(img,str)]
        rows,_=catalog_rows({'products':[{**product,'variants':variants,'images':images}]},host,'Shopify')
        found.extend(rows)
        if product.get('price_min',product.get('price',0))>0:break
    return found,read


def catalog_rows(payload,host,platform):
    items=payload if isinstance(payload,list) else payload.get('products',[])
    out=[]
    for p in items:
        from cero.freecheck import internal_product_reason
        if internal_product_reason(p.get('permalink') or '/products/'+p.get('handle',''),p.get('title') or p.get('name',''),p.get('tags') if platform=='Shopify' else [],p.get('description') or ''):continue
        if platform=='WooCommerce':
            values=p.get('prices') or {};minor=int(values.get('currency_minor_unit',2))
            if values.get('currency_code',CURRENCY)!=CURRENCY:continue
            try:price=int(values['price'])/10**minor;ref=int(values.get('regular_price') or 0)/10**minor
            except (KeyError,ValueError,TypeError):continue
            if p.get('is_virtual') or p.get('is_downloadable') or p.get('is_password_protected'):continue
            variants=[{'title':p.get('name',''),'url':p.get('permalink',''),'price':price,'reference_price':ref,
                       'availability':'in_stock' if p.get('is_in_stock') is True else 'out_of_stock' if p.get('is_in_stock') is False else 'unknown',
                       'image':next((x.get('src','') for x in p.get('images',[]) if x.get('src')),'')}]
        else:
            variants=[]
            for v in p.get('variants',[]):
                try:price=float(v['price']);ref=float(v.get('compare_at_price') or 0)
                except (KeyError,ValueError,TypeError):continue
                variants.append({'title':p.get('title',''),'url':f'https://{host}/products/{p["handle"]}?variant={v["id"]}',
                     'price':price,'reference_price':ref,'variant':v.get('title',''),
                     'availability':'in_stock' if v.get('available') is True else 'out_of_stock' if v.get('available') is False else 'unknown',
                     'image':next((x.get('src','') for x in p.get('images',[]) if x.get('src')),'')})
        for d in variants:
            d.update(discount_pct=discount_pct(d['price'],d['reference_price']),source='Descubrimiento '+platform,
                     store=host,reference_source='Referencia del catálogo público')
            if candidate(d):out.append(d)
    return out,len(items)


def catalog_probe(store,page):
    host=store['domain'];platform=store['platform'];base=store['url'].rstrip('/')
    if platform=='WooCommerce':
        # El cero y la rebaja positiva son consultas distintas: no limitar todo a max_price=0.
        path='/wp-json/wc/store/v1/products?per_page=100&orderby=price&order=asc&'
        urls=[base+path+f'max_price=1&page={page}',base+path+f'on_sale=true&page={page}']
    else:urls=[base+f'/products.json?limit=250&page={page}']
    found=[];read=0
    for url in urls:
        t=datetime.now(timezone.utc)
        try:
            code,body,final=http.get(url,timeout=9,headers={'Accept':'application/json'})
            if code!=200 or http._blocked(code,body):
                health(host+' · catálogo ampliado','catalogue',url,'blocked' if http._blocked(code,body) else 'error',0,detail=f'HTTP {code}')
                break
            payload=json.loads(body);rows,n=catalog_rows(payload,host,platform);found.extend(rows);read+=n
            health(host+' · catálogo ampliado','catalogue',url,'ok' if n else 'empty',(datetime.now(timezone.utc)-t).total_seconds(),n,f'{len(rows)} candidatos de precio cero o descuento >=80%')
        except Exception as exc:health(host+' · catálogo ampliado','catalogue',url,'error',0,detail=type(exc).__name__)
    if platform=='Shopify':
        try:
            cheap,n=shopify_price_floor(store);found.extend(cheap);read+=n
        except Exception:pass  # A failed cheap-first view must not lose the feed.
    return list({canonical(d['url']):d for d in found}.values()),read


def sitemap_probe(store):
    base=store['url'].rstrip('/');host=store['domain'];links=[]
    try:
        code,robots,_=http.get(base+'/robots.txt',timeout=7)
        maps=re.findall(r'^Sitemap:\s*(https?://\S+)',robots,re.I|re.M) if code==200 else []
        maps=[u for u in maps if host_of(u)==host][:2] or [base+'/sitemap.xml']
        visited=set()
        while maps and len(visited)<3:
            url=maps.pop(0)
            if url in visited:continue
            visited.add(url);code,body,_=http.get(url,timeout=8)
            if code!=200 or http._blocked(code,body):continue
            root=ET.fromstring(body)
            if root.tag.endswith('sitemapindex'):
                leaves=[x.text for x in root.findall('.//{*}loc') if x.text and host_of(x.text)==host]
                leaves.sort(key=lambda u:('product' not in u and 'producto' not in u,u))
                maps.extend(leaves[:2]);continue
            rows=[]
            for node in root.findall('.//{*}url'):
                loc=node.find('{*}loc');stamp=node.find('{*}lastmod')
                if loc is None or not loc.text:continue
                u=loc.text
                if host_of(u)!=host or not allowed(u,True) or re.search('/(?:category|categoria|blog|tag|brand|marca)/',u):continue
                if re.search(r'/products?/|/producto/|\.html(?:\?|$)',u):rows.append((stamp.text if stamp is not None else '',u))
            links.extend(u for _,u in sorted(rows,reverse=True)[:12])
        health(host+' · sitemap','sitemap',base,'ok' if links else 'empty',0,len(links),'Productos recientes anunciados en mapas públicos')
    except Exception as exc:health(host+' · sitemap','sitemap',base,'error',0,detail=type(exc).__name__)
    return [{'url':u,'source':'Sitemap de productos recientes'} for u in dict.fromkeys(links)]


def collect(profile='normal',log=None,on_candidates=None,stop=None):
    log=log or print;c=connect();cursor=setting(c,'frontier_cursor',0)
    allstores=[dict(r) for r in c.execute("SELECT * FROM stores WHERE enabled=1 AND platform IN ('WooCommerce','Shopify') ORDER BY domain")]
    n=min(len(allstores),100 if profile=='deep' else 40)
    chosen=[allstores[(cursor+i)%len(allstores)] for i in range(n)] if allstores else []
    page=1+(cursor//max(1,len(allstores)))%4
    set_setting(c,'frontier_cursor',cursor+n)
    due={r['name'] for r in c.execute('SELECT name FROM source_health WHERE next_retry>? AND failures>=2',(now(),))}
    chosen=[s for s in chosen if s['domain']+' · catálogo ampliado' not in due]
    recent=(datetime.now(timezone.utc)-timedelta(hours=4)).isoformat(timespec='seconds')
    checked={canonical(r['url']) for r in c.execute('SELECT url FROM deals WHERE checked_at>?',(recent,))}
    mapstores=[dict(r) for r in c.execute("SELECT * FROM stores WHERE enabled=1 AND platform IN ('PrestaShop','Magento','HTML / schema.org') AND status='ok' ORDER BY domain")]
    mc=setting(c,'sitemap_cursor',0);maps=[mapstores[(mc+i)%len(mapstores)] for i in range(min(3,len(mapstores)))] if mapstores else []
    set_setting(c,'sitemap_cursor',mc+len(maps));c.commit();c.close()
    total=0;allrows=[];seen=set()
    with ThreadPoolExecutor(max_workers=10) as pool:
        tasks={pool.submit(catalog_probe,s,page):'catalog' for s in chosen}
        tasks.update({pool.submit(sitemap_probe,s):'sitemap' for s in maps})
        for future in as_completed(tasks):
            if stop and stop():
                for f in tasks:f.cancel()
                break
            try:
                result=future.result();rows,read=result if tasks[future]=='catalog' else (result,len(result));total+=read
            except Exception:continue
            fresh=[]
            for d in rows:
                u=canonical(d['url'])
                if u in seen or u in checked:continue
                seen.add(u);fresh.append(d)
            # Los nuevos ceros se verifican antes que descuentos y entradas sin precio.
            fresh.sort(key=lambda d:(d.get('price')==0,d.get('availability')=='in_stock',d.get('discount_pct') or 0),reverse=True)
            fresh=fresh[:8];allrows.extend(fresh)
            if on_candidates and fresh:on_candidates(fresh)
    log(f'Exploración nueva: {len(chosen)} catálogos, {len(maps)} sitemaps, {total} productos leídos, {len(allrows)} candidatos nuevos para comprobar.')
    return allrows,total
