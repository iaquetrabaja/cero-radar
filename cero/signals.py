"""Avisos de comunidades: pistas, nunca precios de tienda confirmados."""
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime,timedelta,timezone
from bs4 import BeautifulSoup
from cero import http
from cero.db import connect,now,setting,set_setting
from cero.market import COUNTRY
from cero.policy import allowed,canonical,host_of
from cero.money import is_sample,is_digital,parse_amount


def init(c):
    c.execute('CREATE TABLE IF NOT EXISTS discovery_leads (source_url TEXT PRIMARY KEY,payload TEXT,seen_at TEXT)')


def save(c,lead):
    init(c)
    key=lead['source_url']+(' | '+lead['url'] if lead.get('url') else '')
    old=c.execute('SELECT payload FROM discovery_leads WHERE source_url=?',(key,)).fetchone()
    merged=json.loads(old[0]) if old else {}
    merged.update(lead)
    c.execute('INSERT OR REPLACE INTO discovery_leads VALUES(?,?,?)',(key,json.dumps(merged,ensure_ascii=False),now()))


def listing(html):
    out=[]
    for a in BeautifulSoup(html,'lxml').select('article'):
        for el in a.select('[data-vue3]'):
            try:t=json.loads(el['data-vue3']).get('props',{}).get('thread',{})
            except (ValueError,TypeError):continue
            if not t.get('threadId') or t.get('price')!=0 or t.get('isExpired') or t.get('type')!='Deal':continue
            title=t.get('title','');host=t.get('linkHost','')
            if is_sample(title) or is_digital(title,host) or re.search(r'env[ií]o gratis|portes gratis|free.to.play|hosting|plugin|emails|serie completa|sorteo|s[oó]lo hoy.*entrada',title,re.I):continue
            if not allowed('https://'+host,True):continue
            link=a.select_one('a.thread-link[href]')
            if not link:continue
            out.append({'title':title,'store':t.get('merchant',{}).get('merchantName') or host,
              'source_url':link['href'],'claimed_price':0,'url':t.get('link') or '',
              'status':'lead','conditions':'Anuncio de una comunidad. Falta comprobar condiciones y precio en la tienda.'})
            break
    return out


def collect(log=None):
    if COUNTRY!='ES':return []
    log=log or print;c=connect();init(c);targets=[]
    try:
        last=setting(c,'last_community',0)
        if time.time()-last<600:return []
        set_setting(c,'last_community',time.time());c.commit()
        started=time.monotonic();read=0
        # RSS oficial enlazado por la comunidad; sus precios no se copian como ofertas.
        code,body,_=http.get('https://www.chollometro.com/rss/nuevos',timeout=9)
        if code==200:
            root=ET.fromstring(body)
            for item in root.findall('./channel/item'):
                read+=1
                desc=BeautifulSoup(item.findtext('description') or '','lxml')
                merchant=item.find('{http://www.pepper.com/rss}merchant')
                title=item.findtext('title') or ''
                price=parse_amount(merchant.get('price')) if merchant is not None else None
                if is_sample(title) or is_digital(title):continue
                for link in desc.select('a[href]'):
                    u=link['href']
                    if allowed(u,True):targets.append({'url':canonical(u),'source':'Comunidad · RSS','title':title})
        code,html,_=http.get('https://www.chollometro.com/search?q=gratis',timeout=9)
        if code==200:
            leads=listing(html)
            for lead in leads:
                save(c,lead)
                if lead.get('url') and allowed(lead['url'],True):targets.append({'url':canonical(lead['url']),'source':'Comunidad · cero anunciado','title':lead['title']})
            log(f'Comunidad: {read} avisos recientes leídos; {len(leads)} pistas físicas a cero para revisar.')
        from cero.hunter import health
        c.commit()
        health('Comunidad · Chollometro','discovery','https://www.chollometro.com/rss/nuevos','ok',time.monotonic()-started,read,'Los avisos se contrastan en la tienda; no confirman precios ni stock.')
        c.commit();return list({d['url']:d for d in targets}.values())[:8]
    except Exception as exc:
        log('Comunidad: lectura pendiente ('+type(exc).__name__+').');return []
    finally:c.close()


def visible():
    c=connect();init(c)
    try:
        cutoff=(datetime.now(timezone.utc)-timedelta(days=3)).isoformat(timespec='seconds')
        rows=[json.loads(r[0]) for r in c.execute('SELECT payload FROM discovery_leads WHERE seen_at>? ORDER BY seen_at DESC',(cutoff,))]
        return [r for r in rows if r.get('image','').startswith('/static/cache/') and r.get('url') and allowed(r['url'],True)]
    finally:c.close()
