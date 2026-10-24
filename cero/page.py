"""Lee una ficha de cualquier tienda y saca productos con precio."""

import json
import re
from html import unescape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from cero.money import (
    country_of,
    discount_pct,
    domain_of,
    guess_type,
    is_sample,
    parse_money,
    percent_in_text,
)

CART_RE = re.compile(
    r"añadir al carrito|añadir a la cesta|agregar al carrito|add to cart|add to basket|"
    r"in den warenkorb|ajouter au panier|aggiungi al carrello|adicionar ao carrinho|"
    r"in winkelwagen|do koszyka|comprar ahora|buy now",
    re.I,
)


def extract_offers(page_url: str, html: str, country_hint: str = "") -> list[dict]:
    if not html or len(html) < 400:
        return []
    soup = BeautifulSoup(html, "lxml")
    offers = _from_jsonld(soup, page_url, country_hint)
    offers += _from_opengraph(soup, page_url, country_hint)
    offers += _from_woo(soup, page_url, country_hint)
    if not offers:
        visible = _from_visible(soup, page_url, country_hint)
        if visible:
            offers.append(visible)
    return _dedupe(offers)


def extract_structured(page_url: str, html: str, country_hint: str = "") -> list[dict]:
    """Solo JSON-LD, Open Graph y fichas WooCommerce. Sin texto suelto."""
    if not html or len(html) < 400:
        return []
    soup = BeautifulSoup(html, "lxml")
    offers = _from_jsonld(soup, page_url, country_hint)
    offers += _from_opengraph(soup, page_url, country_hint)
    offers += _from_woo(soup, page_url, country_hint)
    return _dedupe(offers)


def _dedupe(offers: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for offer in offers:
        key = (
            (offer.get("title") or "").lower()[:80],
            offer.get("price"),
            domain_of(offer.get("url") or ""),
        )
        if key in seen or not offer.get("title"):
            continue
        seen.add(key)
        out.append(offer)
    return out


def _base_deal(title, url, price, currency, reference, page_url, country_hint, image="", category=""):
    if price is None or price < 0 or not title or len(title) < 3:
        return None
    title = re.sub(r"\s+", " ", unescape(title)).strip()[:180]
    currency = currency or "EUR"
    if reference is not None and reference <= price:
        reference = None
    pct = discount_pct(price, reference)
    sample = is_sample(title, url)
    country = country_of(url or page_url, currency) or country_hint or ""
    return {
        "source": "web",
        "country": country,
        "store": domain_of(url or page_url),
        "title": title,
        "url": url or page_url,
        "image": image or "",
        "category": category or guess_type(title),
        "product_type": guess_type(title, category),
        "price": price,
        "reference_price": reference,
        "currency": currency,
        "discount_pct": 100.0 if price == 0 else pct,
        "is_free": price == 0,
        "is_sample": sample,
        "kind": "gratis" if price == 0 and not sample else "chollo",
    }


def _image_of(node) -> str:
    image = node.get("image") if isinstance(node, dict) else None
    if isinstance(image, str):
        return image
    if isinstance(image, list) and image:
        return _image_of({"image": image[0]})
    if isinstance(image, dict):
        return image.get("url") or image.get("contentUrl") or ""
    return ""


def _from_jsonld(soup: BeautifulSoup, page_url: str, country_hint: str) -> list[dict]:
    found = []
    for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        raw = script.string or script.get_text() or ""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        _walk_ld(data, page_url, country_hint, found)
    return found


def _walk_ld(node, page_url, country_hint, found, seen=None, depth=0):
    if depth > 8:
        return
    if seen is None:
        seen = set()
    if isinstance(node, list):
        for item in node:
            _walk_ld(item, page_url, country_hint, found, seen, depth + 1)
        return
    if not isinstance(node, dict) or id(node) in seen:
        return
    seen.add(id(node))
    types = node.get("@type") or []
    if isinstance(types, str):
        types = [types]
    if any(t in ("Product", "ProductGroup") for t in types):
        found.extend(_product_ld(node, page_url, country_hint))
        return
    for value in node.values():
        if isinstance(value, (dict, list)):
            _walk_ld(value, page_url, country_hint, found, seen, depth + 1)


def _product_ld(node: dict, page_url: str, country_hint: str) -> list[dict]:
    title = node.get("name") or ""
    image = _image_of(node)
    category = node.get("category") or ""
    if isinstance(category, dict):
        category = category.get("name") or ""
    url = node.get("url") or page_url
    raw_offers = node.get("offers") or []
    if isinstance(raw_offers, dict):
        raw_offers = [raw_offers]
    parsed = []
    for offer in raw_offers:
        if not isinstance(offer, dict):
            continue
        currency = offer.get("priceCurrency") or ""
        high = _num(offer.get("highPrice"))
        low = _num(offer.get("lowPrice"))
        price = _num(offer.get("price"))
        if price is None:
            price = low
        # highPrice es el precio máximo entre ofertas, no un precio anterior.
        reference = None
        spec = offer.get("priceSpecification")
        if isinstance(spec, dict):
            spec = [spec]
        if isinstance(spec, list):
            for item in spec:
                if not isinstance(item, dict):
                    continue
                kind = str(item.get("priceType") or "")
                value = _num(item.get("price"))
                if value is None:
                    continue
                if "ListPrice" in kind or "MSRP" in kind or "StrikethroughPrice" in kind:
                    if reference is None or value > reference:
                        reference = value
                elif "SalePrice" in kind and (price is None or value < price):
                    price = value
        seller = offer.get("seller")
        store = seller.get("name") if isinstance(seller, dict) else ""
        offer_url = urljoin(page_url, offer.get("url") or url)
        deal = _base_deal(title, offer_url, price, currency, reference, page_url, country_hint, image, str(category))
        if not deal:
            continue
        if store:
            deal["store"] = store
        parsed.append(deal)
    return parsed


def _num(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    amount, _cur = parse_money(str(value))
    return amount


def _from_opengraph(soup: BeautifulSoup, page_url: str, country_hint: str) -> list[dict]:
    def meta(prop):
        tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        return tag.get("content", "") if tag else ""

    amount = meta("product:price:amount") or meta("og:price:amount")
    if amount == "":
        return []
    price, _ = parse_money(amount)
    currency = (meta("product:price:currency") or meta("og:price:currency") or "EUR").upper()
    reference, _ = parse_money(meta("product:original_price:amount"))
    title = meta("og:title") or (soup.title.get_text(" ", strip=True) if soup.title else "")
    image = meta("og:image")
    deal = _base_deal(title, page_url, price, currency, reference, page_url, country_hint, image)
    return [deal] if deal else []


def _from_woo(soup: BeautifulSoup, page_url: str, country_hint: str) -> list[dict]:
    cards = soup.select("li.product, div.product.type-product")
    found = []
    for card in cards:
        title_el = card.select_one(".woocommerce-loop-product__title, .woocommerce-loop-product__title, h2, h3, .product-title")
        if not title_el:
            continue
        link = card.select_one("a[href]")
        url = link.get("href") if link else page_url
        price_el = card.select_one("ins .woocommerce-Price-amount, ins .amount, .price ins .amount")
        if price_el is None:
            price_el = card.select_one(".price .woocommerce-Price-amount, .price .amount, .woocommerce-Price-amount")
        old_el = card.select_one("del .woocommerce-Price-amount, del .amount")
        if price_el is None:
            continue
        price, currency = parse_money(price_el.get_text(" ", strip=True))
        reference, _ = parse_money(old_el.get_text(" ", strip=True)) if old_el else (None, None)
        image_el = card.select_one("img")
        image = ""
        if image_el:
            image = image_el.get("src") or image_el.get("data-src") or ""
        deal = _base_deal(
            title_el.get_text(" ", strip=True),
            url,
            price,
            currency,
            reference,
            page_url,
            country_hint,
            image,
        )
        if deal:
            found.append(deal)
    if found:
        return found
    price_el = soup.select_one(
        ".summary ins .woocommerce-Price-amount, .summary ins .amount, "
        ".summary .price .woocommerce-Price-amount, .summary .price .amount"
    )
    old_el = soup.select_one(".summary del .woocommerce-Price-amount, .summary del .amount")
    title_el = soup.select_one("h1.product_title, h1.entry-title, h1")
    if price_el is None or title_el is None:
        return found
    price, currency = parse_money(price_el.get_text(" ", strip=True))
    reference, _ = parse_money(old_el.get_text(" ", strip=True)) if old_el else (None, None)
    deal = _base_deal(title_el.get_text(" ", strip=True), page_url, price, currency, reference, page_url, country_hint)
    if deal:
        found.append(deal)
    return found


def _from_visible(soup: BeautifulSoup, page_url: str, country_hint: str) -> dict | None:
    text = soup.get_text(" ", strip=True)
    if not CART_RE.search(text):
        return None
    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else (soup.title.get_text(" ", strip=True) if soup.title else "")
    window = text[:6000]
    amounts = []
    for match in re.finditer(
        r"(?:€|£|\$)?\s*\d{1,5}(?:[.\s]\d{3})*(?:[.,]\d{2})\s*(?:€|£|\$|EUR|USD|GBP)?",
        window,
    ):
        amount, currency = parse_money(match.group(0))
        if amount is None:
            continue
        amounts.append((amount, currency or "EUR"))
    if not amounts:
        return None
    zeros = [item for item in amounts if item[0] == 0]
    pct = percent_in_text(window)
    price = zeros[0][0] if zeros else min(amounts, key=lambda item: item[0])[0]
    currency = (zeros or amounts)[0][1]
    others = [item[0] for item in amounts if item[0] > price]
    reference = max(others) if others else None
    if pct and pct >= 90 and price > 0:
        guessed = round(price / (1 - pct / 100), 2)
        if reference is None or guessed > reference:
            reference = guessed
    if price != 0 and (pct or 0) < 90 and (reference is None or price > reference * 0.3):
        return None
    return _base_deal(title, page_url, price, currency, reference, page_url, country_hint)
