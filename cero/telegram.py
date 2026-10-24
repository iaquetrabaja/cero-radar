"""Avisos preparados en bandeja local. El envío queda desactivado hasta una activación explícita."""
import json
import os
import html
import io
import re
from datetime import datetime,timezone
from cero.db import now


def enqueue(conn,deal_id,deal):
    if deal.get('status')!='verified' or deal.get('is_sample') or deal.get('image_status')!='verified':return
    if deal.get('price')!=0 and (deal.get('discount_pct') or 0)<80:return
    if deal.get('price')!=0 and (deal.get('score') or 0)<85:return
    previous=conn.execute('SELECT status FROM observations WHERE deal_id=? ORDER BY id DESC LIMIT 1 OFFSET 1',(deal_id,)).fetchone()
    restocked=bool(previous and previous['status']=='expired')
    conn.execute('''INSERT INTO notifications(deal_id,payload,created_at) VALUES(?,?,?)
      ON CONFLICT(deal_id,channel) DO UPDATE SET payload=excluded.payload,created_at=excluded.created_at,
      sent_at=CASE WHEN ? OR json_extract(excluded.payload,'$.price')<COALESCE(json_extract(notifications.payload,'$.price'),1e12)
      THEN NULL ELSE notifications.sent_at END''',
      (deal_id,json.dumps({'title':deal.get('title'),'url':deal.get('url'),'price':deal.get('price'),
                          'variant':deal.get('variant'),'score':deal.get('score')},ensure_ascii=False),now(),int(restocked)))


def armed():
    from cero.config import TELEGRAM_BOT_TOKEN,TELEGRAM_CHAT_ID
    return os.environ.get('TELEGRAM_ENABLED','false').lower()=='true' and bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

def send_deal(deal):
    if not armed() or deal.get('status')!='verified' or deal.get('is_sample') or deal.get('image_status')!='verified':return False
    if not deal.get('checked_at') or (datetime.now(timezone.utc)-datetime.fromisoformat(deal['checked_at'])).total_seconds()>7200:return False
    if deal.get('price')!=0 and (deal.get('discount_pct') or 0)<80:return False
    image=deal.get('image','')
    if not re.fullmatch(r'/static/cache/[a-f0-9]{64}\.webp',image):return False
    from pathlib import Path
    from cero.config import TELEGRAM_BOT_TOKEN,TELEGRAM_CHAT_ID
    from cero.policy import affiliate_url
    from PIL import Image
    from curl_cffi import requests
    path=Path(__file__).parent/'static'/'cache'/Path(image).name
    if not path.exists():return False
    with Image.open(path) as im:
        buffer=io.BytesIO();im.convert('RGB').save(buffer,format='JPEG',quality=88)
    title=html.escape(deal.get('title','')[:180]);url=html.escape(affiliate_url(deal['url']),quote=True)
    price=deal.get('price');currency=html.escape(deal.get('currency') or 'EUR');store=html.escape(deal.get('store',''))
    shipping='Envío por confirmar' if deal.get('shipping') is None else f"Gastos mostrados: {deal['shipping']:.2f} {currency}"
    caption=f'<b>{title}</b>\n{price:.2f} {currency} · {store}\n{shipping}\n<a href="{url}">Ver en tienda</a>'
    try:
        response=requests.post(f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto',data={'chat_id':TELEGRAM_CHAT_ID,'caption':caption,'parse_mode':'HTML'},files={'photo':('producto.jpg',buffer.getvalue(),'image/jpeg')},timeout=20)
        return response.status_code==200 and response.json().get('ok') is True
    except Exception:return False

def send_note(text):return False

def send_hello(text):return False
