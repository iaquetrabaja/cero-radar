"""Exploración incremental dedicada a precios cero con variantes agotadas.

Los filtros sólo descubren candidatos: nunca acreditan precio, stock o compra.
Cada resultado vuelve a pasar por la ficha, su imagen y la revisión de Gemini.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timedelta,timezone
from urllib.parse import urljoin,urlparse
from bs4 import BeautifulSoup
from cero import http
from cero.db import connect,setting,set_setting,now
from cero.frontier import catalog_rows
from cero.hunter import health
from cero.money import is_sample,is_digital
from cero.policy import canonical,host_of


def exhausted_zeros(rows):
    return [r for r in rows if r.get('price')==0 and r.get('availability')=='out_of_stock'
            and r.get('image') and not is_sample(r.get('title',''),r['url'])
            and not is_digital(r.get('title',''),r['url'])]


def product_handles(body,root):
    soup=BeautifulSoup(body,'lxml')
    grid=soup.select_one('#product-grid,.product-grid,[data-product-grid],#main-collection-product-grid,main') or soup
    handles=[]
    for a in grid.select('a[href*="/products/"]'):
        target=urljoin(root,a['href']);m=re.search(r'/products/([^/?#]+)',urlparse(target).path)
        if m and host_of(target)==host_of(root) and m[1] not in handles:handles.append(m[1])
    return handles[:100]


def probe(store,state=None):
    """Return exact zero/OOS candidates and cursors, including pages beyond four."""
    state=dict(state or {});page=max(1,int(state.get('page',1)))
    root=store['url'].rstrip('/');host=store['domain'];platform=store['platform']
    rows=[];read=0;errors=[];success=False;endpoint=root
    if platform=='WooCommerce':
        # Some implementations treat max_price=0 as an empty filter. One minor
        # unit keeps it active; the local comparison below still requires ZERO.
        endpoint=root+f'/wp-json/wc/store/v1/products?per_page=100&max_price=1&stock_status[]=outofstock&orderby=price&order=asc&page={page}'
    else:endpoint=root+f'/products.json?limit=250&page={page}'
    try:
        code,body,_=http.get(endpoint,timeout=9,headers={'Accept':'application/json'})
        if code==200 and not http._blocked(code,body):
            payload=json.loads(body)
            items=payload if isinstance(payload,list) else payload.get('products')
            if not isinstance(items,list):raise ValueError('No es un catálogo de productos')
            found,n=catalog_rows(payload,host,platform);read+=n;success=True
            rows.extend(exhausted_zeros(found))
            signature=[str(p.get('id','')) for p in items[:1]+items[-1:]]
            repeated=page>1 and signature==state.get('signature')
            state.update(page=page+1 if n==(100 if platform=='WooCommerce' else 250) and not repeated else 1,signature=signature)
        elif code==400 and page>1:state['page']=1  # Woo: page beyond the last result.
        else:errors.append(f'catálogo HTTP {code}')
    except Exception as exc:errors.append('catálogo '+type(exc).__name__)
    if platform=='Shopify':
        cp=max(1,int(state.get('collection_page',1)));offset=max(0,int(state.get('offset',0)))
        collection=root+f'/collections/all?sort_by=price-ascending&filter.v.availability=0&filter.v.price.lte=0&page={cp}'
        try:
            code,body,_=http.get(collection,timeout=9)
            if code==200 and not http._blocked(code,body):
                success=True;handles=product_handles(body,root)
                if offset>=len(handles):offset=0
                # Unlike a cheap-first scan, do not stop at a positive product:
                # filters can be unsupported or apply to different variants.
                for handle in handles[offset:offset+8]:
                    try:
                        code,text,_=http.get(root+'/products/'+handle+'.js',timeout=8)
                        if code!=200:continue
                        p=json.loads(text);read+=1
                        if p.get('handle')!=handle:continue
                        variants=[{**v,'price':v['price']/100,'compare_at_price':(v.get('compare_at_price') or 0)/100}
                                  for v in p.get('variants',[]) if type(v.get('price')) in (int,float) and v.get('available') is False]
                        images=[{'src':urljoin(root,img)} for img in p.get('images',[]) if isinstance(img,str)]
                        found,_=catalog_rows({'products':[{**p,'variants':variants,'images':images}]},host,'Shopify')
                        rows.extend(exhausted_zeros(found))
                    except Exception as exc:errors.append('variante '+type(exc).__name__)
                more=offset+8<len(handles)
                has_next=bool(BeautifulSoup(body,'lxml').select_one('a[rel="next"]'))
                state.update(offset=offset+8 if more else 0,collection_page=cp if more else cp+1 if has_next else 1)
        except Exception as exc:errors.append('colección '+type(exc).__name__)
    rows=list({canonical(r['url']):{**r,'source':'Exploración específica · ceros agotados'} for r in rows}.values())
    health(host+' · ceros agotados','restock_discovery',endpoint,'ok' if success else 'error',0,read,
           f'{len(rows)} candidatos; página siguiente {state.get("page",page)}. '+', '.join(errors)[:100])
    return rows,read,state


def diverse_candidates(rows,known=(),limit=8):
    """One product before its second size; never fill a pass with one size run."""
    groups={};seen=set(known)
    for r in rows:
        key=canonical(r['url'])
        if key in seen:continue
        seen.add(key);parent=key.split('?')[0];groups.setdefault(parent,[]).append(r)
    selected=[]
    while groups and len(selected)<limit:
        for parent in list(groups):
            selected.append(groups[parent].pop(0))
            if not groups[parent]:del groups[parent]
            if len(selected)>=limit:break
    return selected


def collect(profile='normal',log=None,on_candidates=None,stop=None):
    log=log or print;c=connect();cursor=setting(c,'stockfinder_cursor',0)
    stores=[dict(r) for r in c.execute("SELECT * FROM stores WHERE enabled=1 AND status='ok' AND platform IN ('WooCommerce','Shopify') ORDER BY domain")]
    n=min(len(stores),50 if profile=='deep' else 20)
    chosen=[stores[(cursor+i)%len(stores)] for i in range(n)] if stores else []
    states=setting(c,'stockfinder_pages',{})
    # Already retained zeros have their own 12-hour clock. Spend discovery time
    # on new variants, not resetting that clock every time a feed repeats them.
    known={canonical(r['url']) for r in c.execute("SELECT url FROM deals WHERE price=0 AND page_status='ok' AND availability='out_of_stock'")}
    retry=(datetime.now(timezone.utc)-timedelta(hours=12)).isoformat(timespec='seconds')
    known.update(canonical(r['url']) for r in c.execute('SELECT url FROM deals WHERE checked_at>?',(retry,)))
    cooling={r['name'] for r in c.execute('SELECT name FROM source_health WHERE next_retry>? AND failures>=2',(now(),))}
    chosen=[s for s in chosen if s['domain']+' · ceros agotados' not in cooling]
    set_setting(c,'stockfinder_cursor',cursor+n);c.commit();c.close()
    total=0;out=[]
    with ThreadPoolExecutor(max_workers=8) as pool:
        tasks={pool.submit(probe,s,states.get(s['domain'])):s for s in chosen}
        for f in as_completed(tasks):
            if stop and stop():
                for other in tasks:other.cancel()
                break
            s=tasks[f]
            try:rows,read,state=f.result()
            except Exception as exc:log(f'Ceros agotados: {s["domain"]}, {type(exc).__name__}.');continue
            total+=read;states[s['domain']]=state
            fresh=diverse_candidates(rows,known,12 if profile=='deep' else 8);known.update(canonical(r['url']) for r in fresh)
            out.extend(fresh)
            if on_candidates and fresh:on_candidates(fresh)
    c=connect();set_setting(c,'stockfinder_pages',states);set_setting(c,'last_stockfinder',now());c.commit();c.close()
    log(f'Ceros agotados: {len(chosen)} tiendas, {total} productos/variantes leídos, {len(out)} candidatos nuevos para verificar.')
    return out,total
