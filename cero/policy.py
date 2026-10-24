"""Ámbito de España y normalización de identidad."""
import ipaddress
import re
import socket
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from cero.retailers import STORES
from cero.market import PROFILE,COUNTRY,LANGUAGE,CUSTOM_STORES

KNOWN = {urlparse(s['url']).hostname.removeprefix('www.'): s['name'] for s in (STORES if COUNTRY=='ES' else [])}
if COUNTRY=='ES':KNOWN.update({'amazon.es':'Amazon','cuatrorayas.es':'Cuatro Rayas'})
KNOWN.update({host['url'].split('/')[2].removeprefix('www.'):host['name'] for host in CUSTOM_STORES})
if PROFILE.get('amazon_domain'):KNOWN[PROFILE['amazon_domain']]='Amazon'
EXCLUDED = {'milanuncios.com','wallapop.com','vinted.es','ebay.es','aliexpress.com',
 'temu.com','facebook.com','instagram.com','pinterest.com','youtube.com',
 'chollometro.com','idealo.es','supersupers.com','google.com','bing.com'}
FOREIGN = {'it','de','fr','pt','uk','nl','be','pl','us','mx','ar','cl','ee','cn','ru'}

def host_of(url):
    return (urlparse(url).hostname or '').lower().removeprefix('www.')

def canonical(url):
    p=urlparse(url);host=(p.hostname or '').lower()
    m=re.search(r'/(?:dp|gp/product)/([A-Z0-9]{10})',p.path)
    if host_of(url)==PROFILE.get('amazon_domain') and m:return 'https://www.'+PROFILE['amazon_domain']+'/dp/'+m[1]
    keep=[(k,v) for k,v in parse_qsl(p.query) if not k.lower().startswith(('utm_','ref','fbclid','gclid','tag'))]
    fragment=p.fragment if re.fullmatch(r'/?sku/\d+',p.fragment,re.I) else ''
    return urlunparse(('https',host,p.path or '/','',urlencode(keep),fragment))

def known_store(url):return KNOWN.get(host_of(url),'')

def affiliate_url(url):
    from cero.config import AMAZON_ASSOCIATE_TAG
    if host_of(url)!=PROFILE.get('amazon_domain'):return url
    clean=canonical(url)
    return clean+('&' if '?' in clean else '?')+urlencode({'tag':AMAZON_ASSOCIATE_TAG}) if AMAZON_ASSOCIATE_TAG else clean

def allowed(url,spanish_evidence=False):
    p=urlparse(url);host=host_of(url)
    try:port=p.port
    except ValueError:return False
    if p.scheme not in ('https','http') or not host or p.username or p.password or port not in (None,80,443):return False
    if any(host==d or host.endswith('.'+d) for d in EXCLUDED):return False
    if host.split('.')[-1] in (FOREIGN|{'es'})-{PROFILE['tld']}:return False
    if re.search(r'/(cart|carrito|cesta|checkout|login|mi-cuenta|account)(/|$)',p.path,re.I):return False
    try:
        if not ipaddress.ip_address(host).is_global:return False
    except ValueError:
        if host=='localhost' or '.' not in host:return False
    return host.endswith('.'+PROFILE['tld']) or host in KNOWN or host=='amzn.eu' or bool(spanish_evidence)

def public_url(url):
    p=urlparse(url)
    try:
        if p.scheme not in ('http','https') or p.username or p.password or p.port not in (None,80,443):return False
        return all(ipaddress.ip_address(a[4][0]).is_global for a in socket.getaddrinfo(p.hostname,p.port or 443))
    except (OSError,ValueError,TypeError):return False

def spanish_page(url,soup):
    if allowed(url):return True
    lang=str((soup.html or {}).get('lang','')).lower()
    if not lang.startswith(LANGUAGE) or not allowed(url,True):return False
    if COUNTRY!='ES' or re.search(r'España|península|peninsula',soup.get_text(' ',strip=True)):return True
    # A product page need not repeat the country in its footer. Retain the
    # independent country evidence from the enabled, analysed store registry.
    from cero.db import connect
    c=connect()
    try:
        row=c.execute("SELECT origin FROM stores WHERE domain=? AND country=? AND enabled=1 AND status='ok'",(host_of(url),COUNTRY)).fetchone()
        return bool(row and re.search(r'España|localizado en España|Configuración personal',row['origin'] or ''))
    finally:c.close()
