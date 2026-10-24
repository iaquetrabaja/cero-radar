"""Datos de la variante Shopify: el formulario inicial puede quedar oculto al cargar JS."""
import json
import re
from urllib.parse import urlparse,parse_qs,parse_qsl,urljoin,urlencode
from cero import http


def apply_variant(deal,product,variant_id):
    from cero.freecheck import internal_product_reason
    reason=internal_product_reason(deal.get('url',''),product.get('title',''),product.get('tags'),product.get('description',''))
    if reason:
        deal.update(status='rejected',free_review='rejected',free_review_reason=reason,conditions=reason,score=0)
        deal.setdefault('evidence',[]).extend([reason,'Etiquetas del catálogo: '+', '.join(product.get('tags') or [])])
        deal.pop('_cart_eligible',None);return
    variants=product.get('variants') or []
    variant=next((v for v in variants if str(v.get('id'))==str(variant_id)),None)
    if not variant:
        deal.update(status='unverified',availability='unknown',conditions='No se encuentra la variante exacta en el catálogo actual de la tienda.')
        deal.pop('_cart_eligible',None);return
    deal['variant']=str(variant.get('public_title') or variant.get('title') or '')
    deal.setdefault('evidence',[]).append(f"Variante Shopify {variant_id}: available={variant.get('available')}.")
    if variant.get('price')!=0:
        price=variant.get('price')
        price=price/100 if type(price) in (int,float) and price>=0 else None
        deal.update(price=price,is_free=False,discount_pct=None,status='unverified',availability='unknown',
                    conditions='El precio de la variante contradice el cero de la plantilla. Se requiere una nueva lectura.')
        deal['evidence'].append(f'Precio actual del catálogo de la variante: {price} {deal.get("currency","EUR")}.')
        deal.pop('_cart_eligible',None);return
    own_image=variant.get('featured_image') or product.get('featured_image') or next(iter(product.get('images') or []),'')
    if isinstance(own_image,dict):own_image=own_image.get('src') or own_image.get('url') or ''
    if own_image:
        deal['image']=urljoin(deal.get('url',''),own_image)
    else:
        deal.update(image='',image_status='missing')
        deal['evidence'].append('El producto no tiene imagen propia en su catálogo; no se utiliza la portada o el logo de la tienda.')
    if type(variant.get('available')) is not bool:
        deal.update(status='unverified',availability='unknown',conditions='El catálogo no declara el stock de la variante exacta.')
        deal.pop('_cart_eligible',None);return
    if variant.get('available') is False:
        deal.update(status='expired',availability='out_of_stock',conditions='Precio cero observado, pero la variante exacta está agotada según la tienda. Revisión cada 12 horas.')
        deal.pop('_cart_eligible',None)
    elif deal.get('availability')=='out_of_stock':
        deal.update(status='candidate',availability='in_stock',conditions='La variante figura de nuevo disponible; falta contrastar la cesta y el envío antes de confirmar el cero.')


def inspect(deal,soup):
    if deal.get('price')!=0:return
    form=soup.select_one('form[action*="cart/add"]')
    p=urlparse(deal['url']);match=re.search(r'/products/([^/]+)',p.path)
    if not match:return
    selected=parse_qs(p.query).get('variant',[''])[0]
    field=form.select_one('input[name="id"],select[name="id"] option[selected]') if form else None
    selected=selected or (field.get('value') if field else '')
    if not str(selected).isdigit():return
    try:
        code,body,_=http.get(f'{p.scheme}://{p.netloc}/products/{match[1]}.js',timeout=8)
        if code!=200:raise ValueError('Catálogo no disponible')
        product=json.loads(body)
        apply_variant(deal,product,selected)
        if any(str(v.get('id'))==str(selected) for v in product.get('variants') or []):
            query=[(key,value) for key,value in parse_qsl(p.query,keep_blank_values=True) if key!='variant']
            query.append(('variant',str(selected)))
            deal['url']=p._replace(query=urlencode(query)).geturl()
    except Exception:
        deal.update(status='unverified',conditions='No se ha podido contrastar el stock de la variante exacta de Shopify.')
        deal.pop('_cart_eligible',None)
