"""Prueba de precio cero en una cesta nueva sin cuentas, direcciones ni pedidos."""
import json
import re
import time
from bs4 import BeautifulSoup
from cero.money import parse_amount
from urllib.parse import urlparse,urljoin,parse_qs
from curl_cffi import requests
from cero.policy import public_url,canonical
from cero.db import connect,now
from cero.market import COUNTRY,CURRENCY


def shopify_cart_evidence(cart,variant):
    items=cart.get('items',[])
    if len(items)!=1 or cart.get('item_count')!=1 or cart.get('currency')!=CURRENCY:return {}
    item=items[0]
    if str(item.get('variant_id') or item.get('id'))!=str(variant) or item.get('quantity')!=1:return {}
    unit=item.get('final_price',item.get('price'));line=item.get('final_line_price',item.get('line_price'))
    return {'item_at_zero':unit==0 and line==0 and cart.get('total_price')==0,
            'needs_shipping':item.get('requires_shipping'),'total_price':cart.get('total_price'),
            'quantity':item['quantity'],'currency':cart['currency'],
            'item_title':item.get('product_title') or item.get('title'),'platform':'Shopify'}


def shopify_shipping_quote(session,root):
    # Public test locality, never the user's address. Other markets need their
    # own validated destination instead of inheriting a Spanish shipping quote.
    if COUNTRY!='ES':return {}
    try:
        destination={
            'shipping_address[country]':'Spain','shipping_address[province]':'Madrid',
            'shipping_address[zip]':'28001'}
        r=session.get(root+'/cart/shipping_rates.json',params=destination,timeout=12,allow_redirects=False)
        if r.status_code!=200:return {'shipping_check':'unavailable'}
        payload=r.json()
        rates=payload.get('shipping_rates',[]) if isinstance(payload,dict) else []
        # Shopify can return no rates while its carrier calculation is pending.
        # Prepare and poll the documented async endpoint, with a strict bound.
        # Never retry HTTP errors or treat a missing quote as free shipping.
        if not rates:
            prepared=session.post(root+'/cart/prepare_shipping_rates.json',params=destination,timeout=12,allow_redirects=False)
            if prepared.status_code in (200,202):
                for attempt in range(3):
                    ready=session.get(root+'/cart/async_shipping_rates.json',params=destination,timeout=12,allow_redirects=False)
                    if ready.status_code!=200:return {'shipping_check':'unavailable'}
                    payload=ready.json()
                    if isinstance(payload,dict):
                        rates=payload.get('shipping_rates',[])
                        break
                    if attempt<2:time.sleep(.6)
        valid=[]
        for rate in rates:
            amount=parse_amount(str(rate.get('price','')))
            if amount is not None and amount>=0 and (rate.get('currency') or CURRENCY)==CURRENCY:
                valid.append({'name':rate.get('name',''),'price':amount})
        if not valid:return {'shipping_check':'no_rates'}
        best=min(valid,key=lambda x:x['price'])
        return {'shipping_check':'quoted','shipping_rates':valid,'shipping_quote_eur':best['price'],
                'shipping_quote_note':f"Cotización de prueba para CP 28001 (Madrid), {best['name']}. Otros destinos y fechas pueden variar.",
                'destination_confirmed':False}
    except Exception:return {'shipping_check':'unavailable'}


def check_free_cart(deal,soup):
    if deal.get('price')!=0 or not deal.get('_cart_eligible'):return None
    origin=urlparse(deal['url']);root=f'{origin.scheme}://{origin.netloc}'
    if not public_url(root):return None
    c=connect()
    try:
        old=c.execute('SELECT payload,checked_at FROM audits WHERE url=?',(canonical(deal['url']),)).fetchone()
        if old:
            from datetime import datetime,timezone
            saved=json.loads(old['payload'])
            if (datetime.now(timezone.utc)-datetime.fromisoformat(old['checked_at'])).total_seconds()<7200 and (saved.get('platform')!='Shopify' or saved.get('audit_version',0)>=2):
                return saved
    finally:c.close()
    proof={'url':deal['url'],'checked_at':now(),'checkout_submitted':False,'item_at_zero':False,'audit_version':2}
    try:
        with requests.Session(impersonate='chrome') as session:
            easy=soup.select_one('form.ec_add_to_cart_form')
            cfg=soup.select_one('#wpeasycart_js-js-extra')
            if easy and cfg:
                match=re.search(r'wpeasycart_ajax_object\s*=\s*(\{.*?\})\s*;',cfg.get_text(),re.S)
                if not match:return None
                options=json.loads(match[1]);endpoint=urljoin(root,options.get('ajax_url',''))
                if urlparse(endpoint).netloc!=origin.netloc or not public_url(endpoint):return None
                pid=easy.select_one('input[name="product_id"]')
                if not pid or not str(pid.get('value','')).isdigit() or not deal.get('sku'):return None
                session.get(deal['url'],timeout=12,allow_redirects=False)
                a=session.post(endpoint,data={'action':'ec_ajax_add_to_cart','product_id':pid['value'],'model_number':deal['sku'],'quantity':1},timeout=12,allow_redirects=False)
                proof['add_status']=a.status_code
                if a.status_code!=200:return _save(proof)
                response=session.post(endpoint,data={'action':'ec_ajax_get_dynamic_cart_page','cart_page':'1','success_code':'','error_code':'','language':options.get('current_language','SP')},timeout=12,allow_redirects=False)
                cart=BeautifulSoup(response.text,'lxml');rows=cart.select('tr.ec_cartitem_row')
                if len(rows)==1:
                    row=rows[0];link=row.select_one('a.ec_cartitem_title');line=row.select_one('.ec_cartitem_total');qty=row.select_one('input.ec_quantity')
                    if link and canonical(link.get('href','')).rstrip('/')==canonical(deal['url']).rstrip('/') and qty and qty.get('value')=='1':
                        total=cart.select_one('#ec_cart_total');shipping=cart.select_one('#ec_cart_shipping_row .ec_cart_price_row_total')
                        total_eur=parse_amount(total.get_text(' ',strip=True)) if total else None
                        ship_eur=parse_amount(shipping.get_text(' ',strip=True)) if shipping else None
                        proof.update(platform='WP EasyCart',item_at_zero=bool(line and parse_amount(line.get_text(' ',strip=True))==0),
                          needs_shipping=True if ship_eur is not None and ship_eur>0 else None,item_title=link.get_text(' ',strip=True),
                          displayed_total_eur=total_eur,shipping_before_tax_eur=ship_eur,destination_confirmed=False)
                return _save(proof)
            form=soup.select_one('form[action*="cart/add"]')
            if form:
                chosen=parse_qs(origin.query).get('variant',[''])[0]
                el=form.select_one('input[name="id"],select[name="id"] option[selected]')
                variant=chosen or (el.get('value') if el else '')
                if not str(variant).isdigit():return None
                endpoint=root+'/cart/add.js'
                response=session.post(endpoint,json={'id':int(variant),'quantity':1},headers={'Accept':'application/json'},timeout=12,allow_redirects=False)
                proof['add_status']=response.status_code
                if response.status_code!=200:return _save(proof)
                cart=session.get(root+'/cart.js',headers={'Accept':'application/json'},timeout=12,allow_redirects=False).json()
                proof.update(shopify_cart_evidence(cart,variant))
                if proof.get('item_at_zero') and proof.get('needs_shipping'):
                    proof.update(shopify_shipping_quote(session,root))
                    latest=session.get(root+'/cart.js',headers={'Accept':'application/json'},timeout=12,allow_redirects=False).json()
                    current=shopify_cart_evidence(latest,variant)
                    proof['item_at_zero']=False
                    proof.update(current)
                return _save(proof)
            button=soup.select_one('form.cart [name="add-to-cart"]')
            if button and str(button.get('value','')).isdigit():
                pid=int(button['value']);r=session.get(root+'/wp-json/wc/store/v1/cart',timeout=12,allow_redirects=False)
                token=r.headers.get('Cart-Token') or r.headers.get('cart-token')
                if not token:
                    from cero.woocheck import woo_classic_rejection
                    rejection=woo_classic_rejection(session,deal,soup,pid)
                    if rejection:proof.update(rejection);return _save(proof)
                    return None
                a=session.post(root+'/wp-json/wc/store/v1/cart/add-item',headers={'Cart-Token':token,'Accept':'application/json'},json={'id':pid,'quantity':1},timeout=12,allow_redirects=False)
                proof['add_status']=a.status_code
                if a.status_code not in (200,201):
                    from cero.woocheck import woo_classic_rejection
                    rejection=woo_classic_rejection(session,deal,soup,pid)
                    if rejection:proof.update(rejection)
                    return _save(proof)
                cart=a.json();items=cart.get('items',[]);matched=[x for x in items if x.get('id')==pid]
                if len(matched)==1 and len(items)==1:
                    item=matched[0];totals=item.get('totals') or {}
                    proof.update(item_at_zero=str(totals.get('line_total'))=='0',needs_shipping=cart.get('needs_shipping'),
                        total_price=(cart.get('totals') or {}).get('total_price'),item_title=item.get('name'),platform='WooCommerce',errors=cart.get('errors',[]))
                return _save(proof)
    except Exception:
        proof['error']='No se pudo completar la cesta de prueba.';return _save(proof)
    return None


def _save(proof):
    c=connect()
    try:c.execute('INSERT OR REPLACE INTO audits VALUES(?,?,?)',(canonical(proof['url']),json.dumps(proof,ensure_ascii=False),proof['checked_at']));c.commit()
    finally:c.close()
    return proof
