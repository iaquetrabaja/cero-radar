"""Buscadores que responden desde esta conexión: Yahoo, Bing, eTools y Swisscows."""

import base64
import re
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from bs4 import BeautifulSoup

from cero import http

SKIP = re.compile(
    r"yahoo\.|bing\.|microsoft\.|google\.|wikipedia\.|youtube\.|facebook\.|instagram\.|"
    r"twitter\.|tiktok\.|reddit\.|pinterest\.|linkedin\.|swisscows\.|etools\.",
    re.I,
)


def search(query: str) -> list[str]:
    urls = []
    for batch in (yahoo(query), bing(query), etools(query), marginalia(query), ddg(query)):
        for url in batch:
            if url not in urls:
                urls.append(url)
    return urls


def google(query: str) -> list[str]:
    url = 'https://www.google.com/search?q=' + quote_plus(query) + '&hl=es&gl=es&num=10&gbv=1'
    status, html, final = http.get(url, timeout=12)
    if status != 200 or '/sorry/' in final:
        return []
    soup = BeautifulSoup(html, 'lxml')
    found = []
    for heading in soup.select('h3'):
        link = heading.find_parent('a', href=True)
        if not link:
            continue
        href = link['href']
        if href.startswith('/url?'):
            href = parse_qs(urlparse(href).query).get('q', [''])[0]
        if href.startswith('http') and not SKIP.search(href):
            found.append(href)
    return _unique(found)[:10]


def yahoo(query: str) -> list[str]:
    url = "https://es.search.yahoo.com/search?p=" + quote_plus(query) + "&ei=UTF-8&fr=sfp"
    status, html, _final = http.get(url, timeout=16)
    if status != 200:
        return []
    found = []
    soup = BeautifulSoup(html, "lxml")
    for link in soup.find_all("a", href=True):
        href = link["href"]
        target = ""
        if "RU=" in href:
            target = unquote(parse_qs(urlparse(href).query).get("RU", [""])[0])
        elif href.startswith("http"):
            target = href
        if target.startswith("http") and not SKIP.search(target):
            found.append(target.split("#")[0])
    return _unique(found)[:8]


def bing(query: str) -> list[str]:
    url = "https://www.bing.com/search?q=" + quote_plus(query) + "&cc=ES&setlang=es-ES"
    status, html, _final = http.get(url, timeout=16)
    if status != 200:
        return []
    soup = BeautifulSoup(html, "lxml")
    found = []
    for link in soup.select("li.b_algo h2 a, li.b_algo a"):
        href = link.get("href") or ""
        target = _unwrap_bing(href)
        if target.startswith("http") and not SKIP.search(target):
            found.append(target.split("#")[0])
    return _unique(found)[:8]


def etools(query: str) -> list[str]:
    url = "https://www.etools.ch/search.do?query=" + quote_plus(query) + "&country=web&language=es&dataSource=all"
    status, html, _final = http.get(url, timeout=16)
    if status != 200:
        return []
    soup = BeautifulSoup(html, "lxml")
    found = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if href.startswith("http") and not SKIP.search(href) and "etools" not in href:
            found.append(href.split("#")[0])
    return _unique(found)[:8]


def marginalia(query: str) -> list[str]:
    url = "https://search.marginalia.nu/search?query=" + quote_plus(query) + "&profile=default"
    return _plain_links(url, "marginalia")


def ddg(query: str) -> list[str]:
    url = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)
    status, html, _final = http.get(url, timeout=16)
    if status != 200:
        return []
    soup = BeautifulSoup(html, "lxml")
    found = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        target = ""
        if "uddg=" in href:
            target = unquote(parse_qs(urlparse(href).query).get("uddg", [""])[0])
        elif href.startswith("http") and "duckduckgo." not in href:
            target = href
        if target.startswith("http") and not SKIP.search(target):
            found.append(target.split("#")[0])
    return _unique(found)[:8]


def swisscows(query: str) -> list[str]:
    return _plain_links("https://swisscows.com/web?query=" + quote_plus(query), "swisscows")


def mojeek(query: str) -> list[str]:
    return _plain_links("https://www.mojeek.com/search?q=" + quote_plus(query), "mojeek")


def qwant(query: str) -> list[str]:
    return _plain_links("https://lite.qwant.com/?q=" + quote_plus(query) + "&locale=es_ES", "qwant")


def brave(query: str) -> list[str]:
    return _plain_links("https://search.brave.com/search?q=" + quote_plus(query) + "&source=web", "brave")


def publicwww(query: str) -> list[str]:
    """Busca el fragmento dentro del HTML publicado, no en el texto visible."""
    url = "https://publicwww.com/websites/" + quote_plus(query) + "/"
    status, html, _final = http.get(url, timeout=16)
    if status != 200:
        return []
    found = []
    for match in re.findall(r"https?://[a-z0-9.-]+\.[a-z]{2,}(?:/[^\s\"'<>]*)?", html, flags=re.I):
        if SKIP.search(match) or "publicwww." in match:
            continue
        found.append(match.split("#")[0])
    return _unique(found)[:8]


def _plain_links(url: str, banned: str) -> list[str]:
    try:
        status, html, _final = http.get(url, timeout=16)
    except Exception:
        return []
    if status != 200 or not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    found = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if not href.startswith("http"):
            continue
        if SKIP.search(href) or banned in href:
            continue
        found.append(href.split("#")[0])
    return _unique(found)[:8]


def _unwrap_bing(href: str) -> str:
    if "/ck/a" not in href and "u=" not in href:
        return href
    query = parse_qs(urlparse(href).query)
    token = (query.get("u") or [""])[0]
    if token.startswith("a1"):
        token = token[2:]
    pad = "=" * (-len(token) % 4)
    try:
        return base64.urlsafe_b64decode(token + pad).decode("utf-8", "ignore")
    except Exception:
        return href


def _unique(urls: list[str]) -> list[str]:
    out = []
    for url in urls:
        if url not in out:
            out.append(url)
    return out
