"""HTTP acotado, con Scrapling y respeto a la cadencia de cada dominio."""
import logging
import threading
import time
from urllib.parse import urljoin
from curl_cffi import requests
from scrapling.fetchers import Fetcher
from cero.policy import public_url

logging.getLogger('scrapling').setLevel(logging.WARNING)
_LAST={};_LOCK=threading.Lock()


def _pause(url):
    from urllib.parse import urlparse
    host=urlparse(url).hostname
    with _LOCK:
        wait=max(0,.6-(time.monotonic()-_LAST.get(host,0)))
        _LAST[host]=time.monotonic()+wait
    if wait:time.sleep(wait)


def _blocked(status,text):
    return status in (403,429,503) or any(s in text[:12000].lower() for s in ('just a moment','cf-browser-verification','robot check','verify you are human','triggerinterstitialchallenge','/errors/validatecaptcha'))


def get(url,headers=None,timeout=15):
    hdrs={'Accept':'text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8','Accept-Language':'es-ES,es;q=0.9,en;q=0.8'}
    hdrs.update(headers or {})
    for _ in range(6):
        if not public_url(url):raise ValueError('URL no pública o no permitida')
        _pause(url)
        # Scrapling se utiliza para HTML y APIs; el seguimiento de redirecciones es explícito.
        response=Fetcher.get(url,headers=hdrs,impersonate='chrome',timeout=timeout,follow_redirects=False,retries=0)
        status=response.status;body=response.body
        text=body.decode('utf-8',errors='replace') if isinstance(body,bytes) else str(body)
        if status in (301,302,303,307,308):
            location=response.headers.get('location') or response.headers.get('Location')
            if not location:return status,text,url
            url=urljoin(url,location);continue
        return status,text[:3_000_000],str(response.url)
    raise ValueError('Demasiadas redirecciones')


def post(url,data,headers=None,timeout=15):
    if not public_url(url):raise ValueError('URL no pública')
    _pause(url)
    r=requests.post(url,data=data,headers=headers or {},impersonate='chrome',timeout=timeout,allow_redirects=False)
    return r.status_code,r.text[:3_000_000]
