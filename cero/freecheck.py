"""Contexto de venta del producto: no confundir un cero técnico con un regalo."""
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup


def internal_product_reason(url,title='',tags=None,description=''):
    path=urlparse(url).path.casefold()
    if isinstance(tags,str):tags=tags.split(',')
    tags={str(t).casefold().strip() for t in (tags or [])}
    if 'sca_clone_freegift' in path or 'bogos-gift' in tags or re.search(r'this product is used for the app\s+bogos',str(description or ''),re.I):
        return 'Ficha interna de regalo promocional BOGOS (sca_clone_freegift/bogos-gift). No es una oferta pública gratuita independiente.'
    if 'qegiftboxhide' in tags:
        return 'Ficha interna oculta de una aplicación de cajas regalo (qegiftboxhide), sin producto independiente identificado.'
    if re.fullmatch(r'tienda\s+(?:on\s*line|virtual)(?:\s+operativa)?',str(title or '').strip(),re.I):
        return 'Página informativa de la tienda publicada como producto; no identifica un artículo físico gratuito.'
    if re.fullmatch(r'(?:(?:primera|segunda|tercera)\s+)?devoluci[oó]n\s+(?:de\s+)?(?:pedido|producto)',str(title or '').strip(),re.I):
        return 'Servicio de devolución de un pedido: no es un producto físico gratuito independiente.'
    return ''


def context(soup):
    # No usar recomendaciones, cesta vacía o promociones del pie como descripción.
    nodes=soup.select('.summary,.product-summary,#tab-description,.woocommerce-product-details__short-description,.product-description,#product-description,.product__description,#description,.ec_details_description')
    if not nodes:nodes=[soup.select_one('main,#main,div.product') or soup.body or soup]
    parts=[]
    for node in nodes:
        copy=BeautifulSoup(str(node),'lxml')
        for x in copy.select('script,style,nav,header,footer,.related,.upsells,.cross-sells,.cart_totals,.widget_shopping_cart'):
            x.decompose()
        text=copy.get_text(' ',strip=True)
        if text and text not in parts:parts.append(text)
    return '\n'.join(parts)[:14000]


def inspect(deal,soup):
    if deal.get('price')!=0:return
    text=context(soup);deal['sale_context']=text
    if re.search(r'lorem ipsum|consectetur adipisicing|texto descriptivo\s*$',text,re.I):
        deal['_zero_template']=True
        deal.update(status='conditional',free_review='uncertain',conditions='La ficha conserva una descripción de plantilla. Se necesita comprobar que la tienda y el producto están realmente a la venta.')
        deal.pop('_cart_eligible',None)
    reason=internal_product_reason(deal.get('url',''),deal.get('title',''),description=text)
    if re.search(r'(?:[úu]nicamente|solo|s[oó]lo|exclusivamente)\s+(?:venta|compra)\s+telef[oó]nica|(?:venta|compra)\s+(?:exclusivamente\s+|solo\s+|[úu]nicamente\s+)?(?:por|v[ií]a)\s+tel[eé]fono',text,re.I):
        reason='Venta únicamente telefónica: el cero de la web no es una oferta gratuita comprable.'
    title=deal.get('title','').strip()
    path=urlparse(deal.get('url','')).path.rstrip('/').split('/')[-1]
    if re.fullmatch(r'(?:prueba|test|dummy|producto[- ]de[- ]prueba)[\s\d_-]*',title,re.I) or re.fullmatch(r'(?:prueba|test|dummy)[\d_-]*',path,re.I):
        reason='Ficha de prueba o marcador técnico; no es un producto gratuito real.'
    if reason:
        deal.update(status='rejected',free_review='rejected',free_review_reason=reason,conditions=reason,score=0,verdict='no_merece')
        deal.setdefault('evidence',[]).append(reason);deal.pop('_cart_eligible',None)
