"""Datos de la variante Shopify: el formulario inicial puede quedar oculto al cargar JS."""
import json
import re
from urllib.parse import urlparse,parse_qs
from cero import http


def apply_variant(deal,product,variant_id):
    variants=product.get('variants') or []
    variant=next((v for v in variants if str(v.get('id'))==str(variant_id)),None)
    if not variant:
        deal.update(status='unverified',availability='unknown',conditions='No se encuentra la variante exacta en el catálogo actual de la tienda.')
        deal.pop('_cart_eligible',None);return
    deal['variant']=str(variant.get('public_title') or variant.get('title') or '')
    deal.setdefault('evidence',[]).append(f"Variante Shopify {variant_id}: available={variant.get('available')}.")
    if variant.get('price')!=0:
        deal.update(status='unverified',conditions='El precio de la variante contradice el cero de la plantilla. Se requiere una nueva lectura.')
        deal.pop('_cart_eligible',None);return
    if not product.get('images') and not product.get('featured_image'):
        deal.update(image='',image_status='missing')
        deal['evidence'].append('El producto no tiene imagen propia en su catálogo; no se utiliza la portada o el logo de la tienda.')
    if variant.get('available') is False:
        deal.update(status='expired',availability='out_of_stock',conditions='Precio cero observado, pero la variante exacta está agotada según la tienda. Revisión cada 12 horas.')
        deal.pop('_cart_eligible',None)


def inspect(deal,soup):
    if deal.get('price')!=0:return
    form=soup.select_one('form[action*="cart/add"]')
    p=urlparse(deal['url']);match=re.search(r'/products/([^/]+)',p.path)
    if not form or not match:return
    selected=parse_qs(p.query).get('variant',[''])[0]
    field=form.select_one('input[name="id"],select[name="id"] option[selected]')
    selected=selected or (field.get('value') if field else '')
    if not str(selected).isdigit():return
    try:
        code,body,_=http.get(f'{p.scheme}://{p.netloc}/products/{match[1]}.js',timeout=8)
        if code!=200:raise ValueError('Catálogo no disponible')
        apply_variant(deal,json.loads(body),selected)
    except Exception:
        deal.update(status='unverified',conditions='No se ha podido contrastar el stock de la variante exacta de Shopify.')
        deal.pop('_cart_eligible',None)
