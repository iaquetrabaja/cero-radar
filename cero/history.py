"""Ejemplos documentados por el usuario, separados de los hallazgos del rastreador."""
import json
from pathlib import Path
from cero.config import ROOT,DATA
from cero.images import cache_image
from cero.policy import affiliate_url,allowed
from cero.market import COUNTRY

EVIDENCE={'spiuk':'historical-spiuk.png','orders':'historical-orders.png'}


def examples():
    if COUNTRY!='ES':return []
    rows=json.loads((ROOT/'catalogs'/'ES-history.json').read_text(encoding='utf-8'))
    for d in rows:
        d['status']='historical';d['source']='Captura aportada por el usuario'
        d['buy_url']=affiliate_url(d['url']) if d.get('url') and allowed(d['url']) else ''
        if d.get('image_url'):d['image']=cache_image(d['image_url'])
        elif d.get('evidence_key'):
            p=DATA/'private-history'/EVIDENCE.get(d['evidence_key'],'missing')
            d['image']='/api/history/image/'+d['evidence_key'] if p.is_file() else ''
        if d.get('reference_price'):
            d['discount_pct']=round((1-d['historical_price']/d['reference_price'])*100,1)
    return rows


def evidence_path(key):
    name=EVIDENCE.get(key)
    p=DATA/'private-history'/name if name else None
    return p if p and p.is_file() else None
