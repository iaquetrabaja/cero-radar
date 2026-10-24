"""Verificación de una ficha. Nunca convierte el total de una cesta o el envío en precio."""
import json
import re
from html import unescape
from difflib import SequenceMatcher
from urllib.parse import urljoin,urlparse
from bs4 import BeautifulSoup
from scrapling.parser import Selector
from cero.money import parse_amount, discount_pct, guess_type, is_sample, is_digital
from cero.policy import canonical, host_of, known_store, spanish_page
from cero.db import now
from cero.images import image_from_page
from cero.taxonomy import classify
from cero.market import COUNTRY,CURRENCY,PROFILE


def numeric(value):
    if value is None or isinstance(value,bool):return None
    try:
        n=float(str(value).replace(',','.'))
        return n if 0<=n<1000000 else None
    except (ValueError,TypeError):return None


def walk(node):
    if isinstance(node,list):
        for x in node:yield from walk(x)
    elif isinstance(node,dict):
        yield node
        for v in node.values():
            if isinstance(v,(dict,list)):yield from walk(v)


def types(n):
    t=n.get('@type',[])
    return [str(x).rstrip('/').split('/')[-1] for x in ([t] if isinstance(t,str) else t)]


def category_of(title):
    return classify(title)['category']


def _image(n):
    x=n.get('image')
    if isinstance(x,list):x=x[0] if x else ''
    if isinstance(x,dict):x=x.get('url','')
    return x or ''


def base(url,title,price,source):
    clean=unescape(BeautifulSoup(unescape(str(title)),'lxml').get_text(' ',strip=True))
    return {'url':canonical(url),'title':re.sub(r'\s+',' ',clean).strip()[:240],
      'price':price,'currency':CURRENCY,'store':known_store(url) or host_of(url),'country':COUNTRY,
      **classify(clean),'source':'ficha',
      'price_source':source,'status':'candidate','availability':'unknown','reference_price':None,
      'reference_source':'','shipping':None,'total_price':None,'is_free':price==0,'is_sample':is_sample(title,url),
      'discount_pct':100 if price==0 else None,'variant':'','image':'','conditions':'',
      'checked_at':now(),'evidence':[],'confidence':40,'kind':'gratis' if price==0 else 'oferta'}


def _main_match(n,url,h1):
    link=n.get('url') or (n.get('mainEntityOfPage') or {})
    if isinstance(link,dict):link=link.get('@id','')
    if link and canonical(urljoin(url,link))!=canonical(url):return False
    title=str(n.get('name',''))
    if h1 and title:
        a=set(re.findall(r'\w+',h1.lower()));b=set(re.findall(r'\w+',title.lower()))
        return len(a&b)/max(1,min(len(a),len(b)))>=.45
    return True


def parse_product(url,html):
    soup=BeautifulSoup(html,'lxml')
    if not spanish_page(url,soup):return []
    if host_of(url)==PROFILE.get('amazon_domain'):return _amazon(url,soup)
    if soup.select_one('#page_data'):
        elc=_elc(url,soup)
        if elc:return elc
    h=soup.select_one('h1.product_title,h1[itemprop="name"],h1')
    h1=h.get_text(' ',strip=True) if h else ''
    records=[];buy_action=False
    # Scrapling estandariza la selección de schemas incluso con HTML defectuoso.
    selector=Selector(html.encode('utf-8'))
    for raw in selector.css('script[type="application/ld+json"]::text').getall():
        try:nodes=list(walk(json.loads(raw)))
        except (ValueError,TypeError):continue
        buy_action=buy_action or any('BuyAction' in types(n) and isinstance(n.get('object'),dict)
                                    and _main_match(n['object'],url,h1) for n in nodes)
        for n in nodes:
            if not any(t in ('Product','ProductGroup') for t in types(n)) or not _main_match(n,url,h1):continue
            if 'ProductGroup' in types(n):continue  # Cada variante tiene su propia ficha/URL.
            offers=n.get('offers') or []
            if isinstance(offers,dict):offers=[offers]
            for offer in offers:
                if not isinstance(offer,dict) or 'AggregateOffer' in types(offer):continue
                price=numeric(offer.get('price'));currency=offer.get('priceCurrency',CURRENCY)
                if price is None or currency!=CURRENCY:continue
                link=urljoin(url,offer.get('url') or n.get('url') or url)
                if canonical(link)!=canonical(url):continue
                d=base(url,h1 or n.get('name',''),price,'schema.org/Offer')
                d['image']=urljoin(url,_image(n)) if _image(n) else '';d['sku']=n.get('sku','')
                d['gtin']=str(n.get('gtin13') or n.get('gtin14') or n.get('gtin12') or n.get('gtin') or '')
                d['evidence'].append(f'Precio del producto: {price:.2f} EUR (schema.org/Offer).')
                avail=str(offer.get('availability','')).split('/')[-1].lower()
                d['availability']={'instock':'in_stock','outofstock':'out_of_stock','soldout':'out_of_stock',
                    'discontinued':'out_of_stock','preorder':'preorder','presale':'preorder','backorder':'preorder'}.get(avail,'unknown')
                d['evidence'].append('Disponibilidad declarada: '+(avail or 'sin datos')+'.')
                specs=offer.get('priceSpecification') or []
                if isinstance(specs,dict):specs=[specs]
                for spec in specs:
                    typ=str(spec.get('priceType',''))
                    if any(x in typ for x in ('StrikethroughPrice','ListPrice','MSRP')):
                        v=numeric(spec.get('price'))
                        if v is not None and v>price:d['reference_price']=v;d['reference_source']='PVP tachado de la tienda'
                shipping=offer.get('shippingDetails') or []
                if isinstance(shipping,dict):shipping=[shipping]
                for ship in shipping:
                    dest=ship.get('shippingDestination',{}).get('addressCountry','')
                    if isinstance(dest,dict):dest=dest.get('name') or dest.get('addressCountry')
                    rate=ship.get('shippingRate',{})
                    if dest in (COUNTRY,PROFILE['name']) or COUNTRY=='ES' and dest=='Spain':
                        if rate.get('currency',CURRENCY)==CURRENCY:d['shipping']=numeric(rate.get('value'))
                records.append(d)
    # WooCommerce visible o metadatos de producto, nunca el precio mínimo de toda la página.
    if not records and h1:
        el=soup.select_one('.summary .price ins .amount,.summary .price .amount,[itemprop="price"][content]')
        meta=soup.select_one('meta[property="product:price:amount"]')
        if el or meta:
            el=el if el is not None else meta
            price=parse_amount(el.get('content') or el.get_text(' ',strip=True))
            if price is not None:
                d=base(url,h1,price,'DOM del producto');old=soup.select_one('.summary .price del .amount')
                if old is not None:
                    ref=parse_amount(old.get_text(' ',strip=True))
                    if ref and ref>price:d['reference_price']=ref;d['reference_source']='PVP tachado de la tienda'
                records.append(d)
    # No buscar CTA en tarjetas de productos relacionados.
    button=soup.select_one('#product-addtocart-button,form.cart button.single_add_to_cart_button,form.cart input[type="submit"],form.ec_add_to_cart_form input[type="submit"],button[data-test="pdp-add-to-cart"],button[data-test="add-to-cart-button"],button[data-testid="add-to-cart-button"],.product-add-to-cart button.add-to-cart,.product-actions button[data-button-action="add-to-cart"],form[action*="cart"] button[name="add"],.product-form__submit')
    purchasable=button is not None and not button.has_attr('disabled') and button.get('aria-disabled')!='true' and 'disabled' not in (button.get('class') or [])
    styles=' '.join(s.get_text() for s in soup.select('style'))
    # Algunos regalos internos publican price=0 pero ocultan expresamente la compra.
    description=soup.select_one('#tab-description,.woocommerce-product-details__short-description,.product__description,.product-description,.product-single__description,[itemprop="description"]')
    desc=description.get_text(' ',strip=True) if description else ''
    hidden=bool(re.search(r'(?:form\.cart|\.single_add_to_cart_button)[^{]*\{[^}]*display\s*:\s*none',styles+' '+desc,re.I))
    conditional=bool(re.search(r'gratis (?:al|por|con) comprar|regalo (?:por|con) (?:la |tu )?compra|pedido m[ií]nimo|solicitar presupuesto|pide presupuesto|solo presupuesto|precio a consultar',desc,re.I))
    for d in records:
        # Un precio tachado sólo se asocia si comparte bloque con el precio actual.
        if d['reference_price'] is None:
            easy=soup.select_one('.ec_details_price')
            current=easy.select_one('.ec_product_sale_price') if easy else None
            old=easy.select_one('.ec_product_old_price') if easy else None
            if current and old and parse_amount(current.get_text('',strip=True))==d['price']:
                ref=parse_amount(old.get_text('',strip=True))
                if ref and ref>d['price']:d['reference_price']=ref;d['reference_source']='PVP tachado de WP EasyCart'
            for price_block in soup.select('[data-testid="price-indication"],[mcclane-data="product-page-price"],.prices,.product-info-price,.summary .price'):
                current=price_block.select_one('[data-testid="price-indication-price"],meta[itemprop="price"],.final-price [mcclane-data="product-price"],.normal-price.special .price,ins .amount')
                old=price_block.select_one('.old-price,del .amount,del')
                value=parse_amount(current.get('content') or current.get_text(' ',strip=True)) if current else None
                ref=parse_amount(old.get_text(' ',strip=True)) if old else None
                if value is not None and abs(value-d['price'])<.005 and ref and ref>d['price']:
                    d['reference_price']=ref;d['reference_source']='PVP tachado de la misma variante en la tienda';break
        d['image']=image_from_page(soup,url,d['image'])
        if d['reference_price'] is None:
            old=soup.select_one('.summary .price del .amount')
            if old:
                ref=parse_amount(old.get_text(' ',strip=True))
                if ref and ref>d['price']:d['reference_price']=ref;d['reference_source']='PVP tachado de la tienda'
        if d['availability']=='unknown' and purchasable:d['availability']='in_stock'
        if d['availability']=='out_of_stock':
            d['status']='expired';d['conditions']='Sin stock.'
            if hidden:d['page_status']='unavailable';d['conditions']='Sin stock y compra oculta por la tienda; no es una oferta de venta pública.'
        elif hidden:d['status']='candidate';d['conditions']='La tienda oculta el precio o el formulario de compra. No se confirma como gratis.'
        elif conditional:d['status']='conditional';d['conditions']='La descripción indica compra adicional o presupuesto. Revisar condiciones.'
        elif (purchasable or (button is None and buy_action and d['price']>0)) and d['availability'] in ('in_stock','preorder'):
            d['status']='verified'
            if d['price']==0:
                d['status']='candidate';d['conditions']='Precio cero publicado con compra activa; falta comprobar una cesta anónima.'
                d['_cart_eligible']=True
        else:d['conditions']='Precio publicado; no se pudo confirmar un botón de compra activo.'
        if purchasable:d['evidence'].append('Botón de compra presente y habilitado en el HTML.')
        if hidden:d['evidence'].append('CSS de la ficha: formulario de compra oculto.')
        if buy_action:d['evidence'].append('La tienda declara BuyAction para el producto.')
        if d['shipping'] is not None:d['total_price']=round(d['price']+d['shipping'],2)
        d['discount_pct']=100 if d['price']==0 else discount_pct(d['price'],d['reference_price'])
        d['confidence']=90 if d['status']=='verified' else 35
        if d['is_sample'] or is_digital(d['title'],url):d['status']='rejected'
        if re.search(r'^(?:gastos de env[ií]o|env[ií]o en caja|presupuesto|solicita presupuesto|muestras?\b|visita\b|entrada\b|donaci[oó]n|tarjeta regalo|cambio de caja|recogida\b|devoluci[oó]n\b)|recoger la anterior',d['title'],re.I):
            d['status']='rejected';d['conditions']='Servicio, muestra o artículo simbólico; no es un producto físico completo.'
        if d['status']=='rejected':d.pop('_cart_eligible',None)
    seen=set();out=[]
    for d in records:
        k=(d['url'],d['variant'],d['price'])
        if k not in seen:seen.add(k);out.append(d)
    return out


def _elc(url,soup):
    """Precios por SKU de ELC: un SKU no comprable no hereda el botón de otro."""
    try:data=json.loads(soup.select_one('#page_data').get_text())
    except (TypeError,ValueError):return []
    selected=re.fullmatch(r'/?sku/(\d+)',urlparse(url).fragment,re.I)
    out=[];seen=set()
    for product in walk(data.get('catalog-spp',{})):
        if not isinstance(product.get('skus'),list):continue
        product_path=urlparse(product.get('url','')).path.rstrip('/')
        if not product_path or not urlparse(url).path.rstrip('/').endswith(product_path):continue
        title=unescape(' '.join(str(product.get(k) or '') for k in ('PROD_RGN_NAME','PROD_RGN_SUBHEADING'))).strip()
        for sku in product['skus']:
            sid=str(sku.get('SKU_BASE_ID') or str(sku.get('SKU_ID','')).removeprefix('SKU'))
            if not sid.isdigit() or sid in seen or (selected and sid!=selected[1]):continue
            seen.add(sid);price=numeric(sku.get('PRICE'))
            if price is None:continue
            link=canonical(url).split('#')[0]+'#/sku/'+sid
            d=base(link,title,price,'Datos de la variante ELC: PRICE')
            d.update(sku='SKU'+sid,variant=sku.get('shadeMenuLabel') or sku.get('PRODUCT_SIZE') or '',gtin=sku.get('UPC_CODE') or '')
            images=sku.get('LARGE_IMAGE_V2') or sku.get('MEDIUM_IMAGE_V2') or []
            if images:d['image']=urljoin(url,images[0])
            ref=numeric(sku.get('PRICE2'))
            if ref and ref>price:d.update(reference_price=ref,reference_source='Precio anterior de la misma variante ELC')
            d['discount_pct']=100 if price==0 else discount_pct(price,ref)
            orderable=sku.get('isOrderable')==1 and sku.get('isShoppable')==1
            if sku.get('isOutOfStock')==1 or sku.get('isSoldOut')==1:
                d.update(status='expired',availability='out_of_stock',conditions='Variante sin stock según sus propios datos.')
            elif not orderable:
                d.update(status='conditional',availability='unknown',page_status='unavailable',conditions='Variante con precio publicado pero bloqueada para pedidos: isOrderable=0 o isShoppable=0. El botón de otra variante no la confirma.')
            else:
                d.update(status='candidate',availability='in_stock',conditions='Precio y variante leídos. Falta confirmar la cesta de esta plataforma.')
            d['evidence']=[f"SKU exacto: {d['sku']}; precio {price} EUR.",f"isOrderable={sku.get('isOrderable')}; isShoppable={sku.get('isShoppable')}; isOutOfStock={sku.get('isOutOfStock')}."]
            out.append(d)
    return out


def _amazon(url,soup):
    title=soup.select_one('#productTitle')
    if title is None:return []
    block=(soup.select_one('#corePriceDisplay_desktop_feature_div')
           or soup.select_one('#corePriceDisplay_mobile_feature_div') or soup.select_one('#corePrice_feature_div'))
    price_el=block.select_one('.a-price:not(.a-text-price) .a-offscreen') if block else None
    price=parse_amount(price_el.get_text(' ',strip=True)) if price_el else None
    if price is None and block:
        accessible=block.select_one('#apex-pricetopay-accessibility-label')
        if accessible:price=parse_amount(accessible.get_text(' ',strip=True))
    if price is None:return []
    d=base(url,title.get_text(' ',strip=True),price,'Amazon: precio principal de la variante')
    old=block.select_one('.a-text-price .a-offscreen')
    if old:
        ref=parse_amount(old.get_text(' ',strip=True))
        if ref and ref>price:d['reference_price']=ref;d['reference_source']='Precio de referencia de Amazon'
    size=soup.select_one('#variation_size_name .selection,#variation_size_name .a-dropdown-prompt')
    if size is None:size=soup.select_one('#inline-twister-expander-content-size_name [data-initiallyselected="true"] .swatch-title-text')
    if size:d['variant']='Talla '+size.get_text(' ',strip=True)
    color=soup.select_one('#variation_color_name .selection')
    if color is None:color=soup.select_one('#inline-twister-expander-content-color_name [data-initiallyselected="true"] .swatch-title-text')
    if color:d['variant']+=' · '+color.get_text(' ',strip=True)
    image=soup.select_one('#landingImage,#imgBlkFront')
    if image:d['image']=image.get('data-old-hires') or image.get('src','')
    btn=soup.select_one('#add-to-cart-button,[name="submit.add-to-cart"]')
    av=soup.select_one('#availability,#availabilityInsideBuyBox_feature_div')
    stock=av.get_text(' ',strip=True) if av else ''
    d['availability']='in_stock' if btn is not None and not btn.has_attr('disabled') else 'unknown'
    if re.search(r'no disponible|sin stock|agotado',stock,re.I):d['availability']='out_of_stock'
    if re.search(r'meses|reserva|temporalmente',stock,re.I) and btn is not None:d['availability']='preorder'
    d['status']='verified' if d['availability'] in ('in_stock','preorder') else 'expired' if d['availability']=='out_of_stock' else 'candidate'
    if price==0 and d['status']=='verified':
        d['status']='candidate';d['conditions']='Precio cero en Amazon; falta comprobar la cesta de esta variante.'
    d['conditions']=' · '.join(filter(None,[d['conditions'],stock]));d['discount_pct']=100 if price==0 else discount_pct(price,d['reference_price'])
    d['evidence']=[f'Precio principal: {price:.2f} EUR.',f'Variante: {d["variant"] or "sin especificar"}.',f'Botón de compra: {"presente" if btn is not None else "no localizado"}.']
    d['confidence']=90 if d['status']=='verified' else 40
    return [d]
