"""Imágenes de producto verificadas y servidas desde una caché local."""
import hashlib
import io
import re
import threading
from pathlib import Path
from urllib.parse import urljoin,urlparse
from PIL import Image,UnidentifiedImageError
from curl_cffi import requests
from cero.config import DATA
from cero.policy import public_url

IMAGES=Path(__file__).resolve().parent/'static'/'cache';IMAGES.mkdir(exist_ok=True)
_LOCK=threading.Lock()
BAD=re.compile(r'placeholder|no[-_]?image|no[-_]?foto|woocommerce-placeholder|(?:^|[/_-])logo(?:[./_-]|$)|blank\.(?:gif|png)|spacer\.',re.I)


def usable(url):
    return bool(url and urlparse(url).scheme in ('http','https') and not BAD.search(url))


def image_from_page(soup,url,preferred=''):
    options=[preferred]
    selectors=['.woocommerce-product-gallery__image img','[data-testid="product-image"] img',
     '[data-testid="product-image"]','img[itemprop="image"]','#landingImage','#imgBlkFront',
     '.product.media img','.product-gallery img','.product-cover img','.images .wp-post-image',
     '.woocommerce-product-gallery img','meta[property="og:image"]']
    for selector in selectors:
        for el in soup.select(selector)[:2]:
            options.append(el.get('data-large_image') or el.get('data-zoom-image') or el.get('data-src') or el.get('src') or el.get('content') or '')
    for candidate in options:
        resolved=urljoin(url,candidate) if candidate else ''
        if usable(resolved):return resolved
    return ''


def cache_image(url):
    if url.startswith('/static/cache/'):
        p=IMAGES/Path(url).name
        return url if p.is_file() else ''
    if not usable(url):return ''
    key=hashlib.sha256(url.encode()).hexdigest()+'.webp';dest=IMAGES/key
    if dest.is_file():return '/static/cache/'+key
    current=url
    try:
        for _ in range(5):
            if not public_url(current):return ''
            r=requests.get(current,headers={'Accept':'image/avif,image/webp,image/*,*/*;q=0.5'},
                           timeout=10,impersonate='chrome',allow_redirects=False)
            if r.status_code in (301,302,303,307,308):current=urljoin(current,r.headers.get('location',''));continue
            if r.status_code!=200 or len(r.content)>12_000_000:return ''
            # Decodificar y re-encodear descarta HTML, SVG activo y archivos que no son fotos válidas.
            with Image.open(io.BytesIO(r.content)) as im:
                if min(im.size)<64 or im.width*im.height>30_000_000:return ''
                im.thumbnail((1000,1000));out=io.BytesIO();im.convert('RGB').save(out,'WEBP',quality=85)
            with _LOCK:
                dest.write_bytes(out.getvalue())
            return '/static/cache/'+key
    except (OSError,ValueError,UnidentifiedImageError,requests.RequestException):return ''
    return ''


def ensure_image(deal):
    original=deal.get('image') or ''
    cached=cache_image(original)
    deal['image']=cached
    deal['image_status']='verified' if cached else 'missing'
    deal['image_source']=original if not original.startswith('/static/cache/') else deal.get('image_source','')
    if not cached:
        evidence=deal.get('evidence') or []
        if isinstance(evidence,list):
            evidence.append('Imagen de producto no disponible o no válida: ficha oculta en el radar hasta conseguirla.')
    return bool(cached)
