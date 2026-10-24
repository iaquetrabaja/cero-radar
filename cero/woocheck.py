"""Rechazos explícitos de WooCommerce mediante el formulario público real.

La ausencia de rechazo no demuestra que un producto sea gratis ni comprable.
Este respaldo no envía pedidos ni datos personales.
"""
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from cero.policy import public_url


_REJECTION = re.compile(
    r'\b(?:este producto no (?:se puede|puede|se podrá) comprar'
    r'|no (?:puedes|puede|se puede) comprar este producto'
    r'|este producto no puede ser comprado'
    r'|este producto no est[aá] (?:disponible para (?:la )?compra|a la venta)'
    r'|(?:this|the) product (?:cannot|can\s*not|can[’\']t) be purchased'
    r'|(?:this|the) product is not (?:purchasable|available for purchase)'
    r'|you (?:cannot|can\s*not|can[’\']t) (?:buy|purchase) this product)\b',
    re.I,
)


def _unrelated(node):
    for ancestor in [node, *node.parents]:
        if not getattr(ancestor, 'select', None):
            continue
        classes = set(ancestor.get('class', [])) if hasattr(ancestor, 'get') else set()
        if ancestor.name in {'header', 'footer', 'nav', 'aside'} or classes & {'related', 'upsells', 'up-sells', 'cross-sells'}:
            return True
    return False


def woo_classic_rejection(session, deal, soup, product_id):
    """Devuelve evidencia de rechazo; nunca confirma una compra ni precio cero."""
    url = deal.get('url', '')
    source = urlparse(url)
    pid = str(product_id)
    if deal.get('price') != 0 or not pid.isdigit() or not source.hostname:
        return None

    def safe(target):
        try:
            parsed = urlparse(target)
            return (parsed.hostname == source.hostname and parsed.scheme in {'http', 'https'}
                    and not parsed.username and not parsed.password and public_url(target))
        except (TypeError, ValueError):
            return False

    if not safe(url):
        return None
    chosen = None
    for form in soup.select('form.cart'):
        if _unrelated(form) or 'variations_form' in form.get('class', []):
            continue
        if form.select_one('select[name^="attribute_"], input[name="variation_id"], .variations'):
            continue
        button = form.select_one('[name="add-to-cart"]')
        if button and not button.has_attr('disabled') and str(button.get('value', '')) == pid:
            chosen = form
            break
    if chosen is None or chosen.get('method', '').lower() != 'post':
        return None
    target = urljoin(url, chosen.get('action') or url)
    if not safe(target):
        return None

    # Only product identity, quantity and CSRF fields are submitted. Hidden
    # address/customer fields and other checkout data are deliberately omitted.
    fields = {}
    for el in chosen.select('input[type="hidden"][name]'):
        name = el['name']
        if name in {'add-to-cart', 'product_id', '_wpnonce'} or re.fullmatch(r'[\w-]*nonce', name, re.I):
            fields[name] = el.get('value', '')
    fields.update({'add-to-cart': pid, 'quantity': '1'})
    if 'product_id' in fields:
        fields['product_id'] = pid

    try:
        method = 'post'
        for redirects in range(4):
            if method == 'post':
                response = session.post(target, data=fields, timeout=12, allow_redirects=False)
            else:
                response = session.get(target, timeout=12, allow_redirects=False)
            if response.status_code not in {301, 302, 303, 307, 308}:
                break
            if redirects == 3:
                return None
            location = response.headers.get('Location') or response.headers.get('location')
            if not location:
                return None
            target = urljoin(target, location)
            if not safe(target):
                return None
            if response.status_code in {301, 302, 303}:
                method = 'get'
        if response.status_code != 200:
            return None
        result = BeautifulSoup(response.text, 'lxml')
        for alert in result.select('.woocommerce-error, [role="alert"]'):
            if _unrelated(alert):
                continue
            text = alert.get_text(' ', strip=True)
            if not _REJECTION.search(text):
                continue
            quote = text[:1000]
            return {
                'purchase_rejected': True,
                'reason': 'La tienda rechaza añadir este producto a la cesta: ' + quote,
                'platform': 'WooCommerce',
                'product_id': int(pid),
                'quantity': 1,
                'checkout_submitted': False,
                'item_at_zero': False,
                'evidence': quote,
                'verification_method': 'classic_product_form',
            }
    except Exception:
        return None
    return None
