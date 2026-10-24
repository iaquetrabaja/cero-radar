"""Saca productos y precios de una página de resultados, de cualquier tienda."""

import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from cero.money import discount_pct, domain_of, guess_type, is_digital, is_sample, parse_amount
from cero.page import extract_structured

CARD_SELECTORS = (
    "li.product",
    "article.product",
    ".ec_product_li",
    ".ec_product_type6",
    "div.product-item",
    "div.product-card",
    "[data-asin]",
    "[data-product-id]",
    "[data-product-name]",
    ".product-miniature",
    ".product-tile",
    ".s-item",
    "[class*='product-card']",
    "[class*='ProductCard']",
    "[class*='productCard']",
    "[class*='product-tile']",
    "[class*='productTile']",
    "[class*='product-item']",
)

SKIP_HREF = re.compile(
    r"/(cart|carrito|cesta|checkout|login|account|customer|wishlist|search|buscar|ayuda|help|legal|privacy|cookie)",
    re.I,
)
EURO_RE = re.compile(
    r"(?:€\s*)?(?P<num>\d{1,3}(?:\.\d{3})*,\d{2}|\d+(?:[.,]\d{2})?)\s*€",
)
SHIP_RE = re.compile(r"env[ií]o|gastos|shipping|cuota|financi|/mes|\bmes\b", re.I)
JSON_NAME = re.compile(
    r'"(?:name|title|productName|product_name|displayName)"\s*:\s*"((?:\\.|[^"\\]){8,160})"',
)
JSON_PRICE = re.compile(
    r'"(?:price|finalPrice|final_price|salePrice|specialPrice|special_price|currentPrice)"\s*:\s*"?(\d+(?:\.\d+)?)"?',
)
JSON_REF = re.compile(
    r'"(?:regularPrice|oldPrice|originalPrice|listPrice|crossedPrice|rrp|wasPrice|priceBefore|pvp)"\s*:\s*"?(\d+(?:\.\d+)?)"?',
)
JSON_URL = re.compile(r'"(?:url|link|productUrl|canonicalUrl|href)"\s*:\s*"((?:https?:)?\\?/\\?/[^"]{8,}|/[^"]{8,})"')

NOUNS = {
    "bicicleta": "bike",
    "bici": "bike",
    "maillot": "shirt",
    "camiseta": "shirt",
    "zapatilla": "shoe",
    "robot": "robot",
    "aspirador": "robot",
    "televisor": "tv",
    "patinete": "scooter",
    "cafetera": "coffee",
    "auricular": "audio",
    "portátil": "laptop",
    "portatil": "laptop",
    "taladro": "tool",
    "sofá": "sofa",
    "sofa": "sofa",
    "perfume": "beauty",
    "lego": "toy",
    "transportín": "pet",
    "transportin": "pet",
    "batería": "auto",
    "bateria": "auto",
    "pala": "padel",
    "iphone": "phone",
    "neopreno": "sport",
    "casco": "sport",
    "crema": "beauty",
    "maceta": "garden",
}

OK = {
    "bike": re.compile(r"bicicleta|\bbici\b|e-?bike|\bmtb\b|gravel|carretera|plegable", re.I),
    "robot": re.compile(r"robot|conga|roomba|roborock|dreame|aspirador", re.I),
    "tv": re.compile(r"televisor|\btv\b|oled|qled|led", re.I),
    "scooter": re.compile(r"patinete", re.I),
    "shirt": re.compile(r"camiseta|maillot|jersey|samarreta", re.I),
    "shoe": re.compile(r"zapatilla|sneaker|runner", re.I),
}

NO = {
    "bike": re.compile(
        r"casco|\bluz\b|sill[ií]n|cubierta|c[aá]mara|candado|portabid|guardabarros|\bbomba\b|"
        r"\bcadena\b|\bpedal|manillar|potencia|\btija\b|funda|alforja|cesta|timbre|espejo|"
        r"portabultos|maillot|culote|guantes|gafas|zapatilla|bid[oó]n|portam[oó]vil|"
        r"herramienta|aceite|parche|ciclocomputador|\bgps\b|puños|cinta de manillar|"
        r"pastilla|zapata|soporte|bolsa de|\bcable\b|marcador|\bruta\b|alquiler|experiencia|\btour\b",
        re.I,
    ),
    "robot": re.compile(r"\bbolsa\b|\bfiltro\b|cepillo|fregona|recambio|repuesto|\bmopa\b|paño|deposito de|depósito", re.I),
    "tv": re.compile(r"soporte|\bmando\b|\bcable\b|peana|bracket|base de pared", re.I),
    "scooter": re.compile(r"casco|candado|\bluz\b|cámara|cubierta|guardabarros suelto", re.I),
    "shoe": re.compile(r"plantilla|cordones|calcetin|calcetín|bolsa para", re.I),
    "laptop": re.compile(r"funda|cargador|ratón|raton|mochila|soporte|pegatina", re.I),
}


def family_of(query: str) -> str:
    low = query.lower()
    for key, family in NOUNS.items():
        if key in low:
            return family
    return ""


def relevant(title: str, family: str) -> bool:
    if not family:
        return True
    ok = OK.get(family)
    bad = NO.get(family)
    if bad and bad.search(title):
        return False
    if ok:
        return bool(ok.search(title))
    return True


def extract_listing(html: str, page_url: str, store: str, query: str) -> list[dict]:
    if not html or len(html) < 800:
        return []
    found: list[dict] = []
    for offer in extract_structured(page_url, html, "ES"):
        offer["store"] = store or offer.get("store") or domain_of(page_url)
        offer["country"] = "ES"
        offer["source"] = offer.get("source") or "tienda"
        found.append(offer)
    soup = BeautifulSoup(html, "lxml")
    cards = []
    for selector in CARD_SELECTORS:
        cards.extend(soup.select(selector))
    seen_nodes = set()
    for card in cards:
        if id(card) in seen_nodes:
            continue
        seen_nodes.add(id(card))
        deal = _from_card(card, page_url, store, query)
        if deal:
            found.append(deal)
    if len(found) < 4:
        found.extend(_from_blobs(html, page_url, store, query))
        found.extend(_from_price_nodes(soup, page_url, store, query))
    # La página de búsqueda y la portada no son un producto. Nunca combinar sus precios.
    return _dedupe([d for d in found if d.get('url') and d['url'].split('?')[0].rstrip('/') != page_url.split('?')[0].rstrip('/')])


def _from_card(card, page_url: str, store: str, query: str) -> dict | None:
    title = ""
    named = card.get("data-product-name")
    if named:
        title = named
    if not title:
        heading = card.select_one("h2, h3, h4, [class*='title'], [class*='name']")
        if heading:
            title = heading.get_text(" ", strip=True)
    link = card.select_one("a[href]")
    href = link.get("href") if link else ""
    if not title and link:
        title = link.get("title") or link.get_text(" ", strip=True)
    if not title or len(title) < 6 or not href:
        return None
    if SKIP_HREF.search(href):
        return None
    url = urljoin(page_url, href)
    if url.split("?")[0].rstrip("/") == page_url.split("?")[0].rstrip("/"):
        return None
    if url.startswith("javascript"):
        return None
    old_el = card.select_one("del, s, [class*='old-price'], [class*='was-price'], [class*='regular-price']")
    reference = _first_euro(old_el.get_text(" ", strip=True)) if old_el else None
    amounts = _euros(card.get_text(" ", strip=True))
    if reference is not None:
        amounts = [a for a in amounts if abs(a - reference) > 0.009]
    if not amounts:
        return None
    price = amounts[0]
    if reference is not None and price > reference:
        price, reference = reference, price
    if reference is not None and reference <= price:
        reference = None
    return _deal(title, url, price, reference, store, page_url, query, explicit_zero=price == 0, trusted=reference is not None)


def _from_blobs(html: str, page_url: str, store: str, query: str) -> list[dict]:
    deals = []
    for match in JSON_NAME.finditer(html):
        window = html[match.end() : match.end() + 800]
        price_m = JSON_PRICE.search(window)
        if not price_m:
            continue
        price = float(price_m.group(1))
        if price > 20000:
            continue
        url_m = JSON_URL.search(window) or JSON_URL.search(html[max(0, match.start() - 500) : match.start()])
        if not url_m:
            continue
        url = url_m.group(1).replace("\\/", "/")
        if url.startswith("//"):
            url = "https:" + url
        url = urljoin(page_url, url)
        if SKIP_HREF.search(url):
            continue
        try:
            title = json.loads(f'"{match.group(1)}"')
        except json.JSONDecodeError:
            title = match.group(1)
        ref_m = JSON_REF.search(window)
        reference = float(ref_m.group(1)) if ref_m else None
        if reference is not None and reference <= price:
            reference = None
        deal = _deal(title, url, price, reference, store, page_url, query, explicit_zero=price == 0, trusted=reference is not None)
        if deal:
            deals.append(deal)
        if len(deals) >= 60:
            break
    return deals


def _euros(text: str) -> list[float]:
    text = (text or "").replace("\xa0", " ")
    text = re.sub(r"(\d)\s+([.,])\s*(\d{2})", r"\1\2\3", text)
    found = []
    for match in EURO_RE.finditer(text):
        start = max(0, match.start() - 36)
        if SHIP_RE.search(text[start : match.end() + 14]):
            continue
        amount = parse_amount(match.group("num"))
        if amount is None or amount > 20000:
            continue
        found.append(amount)
    return found


def _from_price_nodes(soup: BeautifulSoup, page_url: str, store: str, query: str) -> list[dict]:
    deals = []
    for el in soup.select("[class*='price'], [class*='Price']"):
        classes = " ".join(el.get("class") or [])
        if any(bit in classes for bit in ("Prefix", "Count", "vat", "Slider", "input", "old", "was", "strike", "before")):
            continue
        price = _first_euro(el.get_text(" ", strip=True))
        if price is None:
            continue
        parent = el
        title = ""
        href = ""
        reference = None
        for _ in range(6):
            if parent is None:
                break
            if not href:
                link = parent.find("a", href=True)
                if link and not SKIP_HREF.search(link.get("href") or ""):
                    href = link["href"]
                    title = link.get("title") or link.get_text(" ", strip=True)
            old = parent.select_one("del, s, [class*='old-price'], [class*='was-price'], [class*='strike']")
            if old is not None and reference is None:
                reference = _first_euro(old.get_text(" ", strip=True))
            if href and title and len(title) > 8:
                break
            parent = getattr(parent, "parent", None)
        if not href or len(title) < 8:
            continue
        url = urljoin(page_url, href)
        if reference is not None and reference <= price:
            reference = None
        deal = _deal(title[:180], url, price, reference, store, page_url, query, explicit_zero=price == 0, trusted=reference is not None)
        if deal:
            deals.append(deal)
        if len(deals) >= 40:
            break
    return deals


def _first_euro(text: str) -> float | None:
    amounts = _euros(text)
    return amounts[0] if amounts else None


def _deal(title, url, price, reference, store, page_url, query, explicit_zero=False, trusted=False) -> dict | None:
    title = re.sub(r"\s+", " ", str(title)).strip()[:180]
    if len(title) < 6:
        return None
    if is_digital(title, url) or is_sample(title, url):
        return None
    if price is None or price < 0:
        return None
    pct = 100.0 if price == 0 and reference else discount_pct(price, reference)
    if price == 0 and not reference:
        pct = 100.0 if explicit_zero else None
    return {
        "source": "tienda",
        "country": "ES",
        "store": store or domain_of(url or page_url),
        "title": title,
        "url": url.split("#")[0],
        "image": "",
        "category": guess_type(query, title),
        "product_type": guess_type(query, title),
        "price": price,
        "reference_price": reference,
        "currency": "EUR",
        "discount_pct": pct,
        "is_free": price == 0,
        "is_sample": False,
        "kind": "gratis" if price == 0 else "chollo",
        "explicit_zero": explicit_zero and price == 0,
        "ref_trusted": bool(trusted and reference and reference > price),
        "query": query,
    }


def _dedupe(deals: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for deal in deals:
        key = (deal.get("url"), deal.get("title"), deal.get("price"))
        if key in seen:
            continue
        seen.add(key)
        out.append(deal)
    return out
