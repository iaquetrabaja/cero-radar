"""Radar compartido de solo lectura, tras la autenticación del proxy de Tools.

Ejecutar en una interfaz interna (por ejemplo 127.0.0.1:8766). El proxy debe
autenticar TODAS las rutas, incluidas API y fotografías. Este proceso no arranca
el rastreador, no llama a modelos y abre la base existente en modo solo lectura.
"""
import hashlib
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from cero.config import DB_PATH, ROOT
from cero.db import query_deals, unpack
from cero.market import COUNTRY, PROFILE
from cero.policy import affiliate_url, allowed


STATIC = Path(__file__).resolve().parent / 'static'
IMAGE_DIR = STATIC / 'cache'
PUBLIC_PREFIX = os.environ.get('CERO_PUBLIC_PREFIX', '/cero/radar').rstrip('/')
if PUBLIC_PREFIX and not re.fullmatch(r'(?:/[A-Za-z0-9_-]+)+', PUBLIC_PREFIX):
    raise ValueError('CERO_PUBLIC_PREFIX debe ser una ruta local sin parámetros.')
BASE_URL = PUBLIC_PREFIX + '/'
app = FastAPI(title='CERO · Radar compartido', root_path=PUBLIC_PREFIX,
              docs_url=None, redoc_url=None, openapi_url=None)

DEAL_FIELDS = {
    'id', 'country', 'store', 'title', 'url', 'image', 'category', 'subcategory',
    'product_type', 'price', 'reference_price', 'reference_source', 'currency',
    'discount_pct', 'score', 'status', 'availability', 'variant', 'shipping',
    'total_price', 'shipping_note', 'reason', 'conditions', 'checked_at',
    'found_at', 'last_verified_at', 'best_price', 'best_discount', 'free_review',
    'free_review_reason', 'verification_level', 'next_review', 'image_status',
}
_INTERNAL_TEXT = re.compile(r'presupuesto|budget|api[_ -]?key|GEMINI_API_KEY|'
                            r'clave.{0,15}api|(?:[A-Z]:\\|/home/|/opt/)|\.env\b', re.I)


@contextmanager
def readonly_connection():
    """No crea bases, migra esquemas ni modifica tablas de gasto/estado."""
    if not Path(DB_PATH).is_file():
        raise HTTPException(503, 'El radar todavía está preparando sus datos.')
    conn = None
    try:
        conn = sqlite3.connect(Path(DB_PATH).resolve().as_uri() + '?mode=ro',
                               uri=True, timeout=8, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        yield conn
    except sqlite3.Error:
        raise HTTPException(503, 'Los datos del radar no están disponibles temporalmente.') from None
    finally:
        if conn is not None:
            conn.close()


def public_text(value):
    text = str(value or '')
    return 'Pendiente de una revisión actualizada.' if _INTERNAL_TEXT.search(text) else text


def public_deal(deal):
    result = {key: deal.get(key) for key in DEAL_FIELDS}
    result['buy_url'] = affiliate_url(deal.get('url') or '')
    result['under_review'] = bool(deal.get('review_hold'))
    result['score_kind'] = 'gemini' if str(deal.get('score_source', '')).startswith('gemini') else 'radar'
    for key in ('reason', 'conditions', 'shipping_note', 'free_review_reason'):
        result[key] = public_text(result.get(key))
    if result['under_review']:
        for key in ('reason', 'conditions', 'free_review_reason'):
            result[key] = 'Pendiente de una revisión adicional de la oferta.'
    # Only validated, inert product images are served by this application.
    if not re.fullmatch(r'/static/cache/[a-f0-9]{64}\.webp', result.get('image') or ''):
        result['image'] = ''
    return result


def visible(rows):
    return [row for row in rows if row.get('status') not in {'rejected', 'merged'}]


@app.middleware('http')
async def read_only(request: Request, call_next):
    if request.method not in {'GET', 'HEAD'}:
        return JSONResponse({'detail': 'Este radar compartido es de solo lectura.'},
                            status_code=405, headers={'Allow': 'GET, HEAD'})
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Cache-Control'] = 'private, max-age=30'
    return response


@app.get('/', response_class=HTMLResponse)
def home():
    document = BeautifulSoup((STATIC / 'index.html').read_text(encoding='utf-8'), 'lxml')
    for selector in ('[data-view="saved"]', '[data-view="watches"]', '[data-view="sources"]',
                     '[data-view="activity"]', '[data-view="settings"]', '.sidebar-bottom',
                     '.head-actions', '#scan-panel', '#watch-dialog', 'script[src]'):
        for node in document.select(selector):
            node.decompose()
    for label in document.select('.nav-label'):
        if 'CONTROL' in label.get_text():
            label.string = 'SEGUIMIENTO'
    document.select_one('.workspace strong').string = 'Radar compartido'
    document.select_one('.brand')['href'] = BASE_URL
    document.select_one('.avatar').string = 'C'
    document.select_one('#radar-status').string = 'Lectura compartida · datos del radar'
    document.select_one('.breadcrumb').contents[0].replace_with('Comunidad ')
    document.select_one('#pending-note').decompose()
    for css in document.select('link[rel="stylesheet"]'):
        css['href'] = BASE_URL + 'static/app.css?v=public-1'
    document.body['class'] = [*document.body.get('class', []), 'public-radar']
    introduction = document.new_tag('section', attrs={'class': 'public-intro panel'})
    introduction.append(BeautifulSoup(
        '<h2>Las joyas tardan en aparecer. Y pueden durar minutos.</h2>'
        '<p>El radar busca productos físicos a 0 € y descuentos de al menos el 80%. '
        'No todas las pasadas encuentran algo nuevo: los errores de precio son excepcionales '
        'y pueden desaparecer antes de la siguiente lectura.</p>'
        '<p>Ya hemos visto una bicicleta Cecotec de 849 € por 72,90 €, un Conga de 399 € '
        'por 22,90 € y maillots Spiuk a 0 €, incluso sin portes en aquella oferta. '
        'Son ofertas pasadas: consulta su sección '
        'para distinguirlas de las oportunidades actuales.</p>'
        '<a class="text-btn" href="https://github.com/iaquetrabaja/cero-radar" '
        'target="_blank" rel="noopener noreferrer">Ver el proyecto y montar tu propio radar en GitHub ↗</a>',
        'html.parser'))
    document.select_one('#stats').insert_after(introduction)
    config = document.new_tag('script')
    config.string = 'window.CERO_PUBLIC=' + json.dumps({'base': BASE_URL}, ensure_ascii=True) + ';'
    document.body.append(config)
    script = document.new_tag('script', src=BASE_URL + 'static/public.js?v=1', defer=True)
    document.body.append(script)
    return HTMLResponse(str(document))


@app.get('/static/app.css')
def stylesheet():
    return FileResponse(STATIC / 'app.css', media_type='text/css')


@app.get('/static/public.js')
def public_script():
    return FileResponse(STATIC / 'public.js', media_type='application/javascript')


@app.get('/static/cache/{key}')
def product_image(key: str):
    if not re.fullmatch(r'[a-f0-9]{64}\.webp', key):
        raise HTTPException(404, 'Imagen no disponible.')
    path = IMAGE_DIR / key
    if not path.is_file():
        raise HTTPException(404, 'Imagen no disponible.')
    return FileResponse(path, media_type='image/webp')


@app.get('/api/meta')
def meta_view():
    with readonly_connection() as conn:
        rows = visible(query_deals(conn, limit=500))
        radar = visible(query_deals(conn, status='radar', limit=500))
        active = [row for row in radar if row['status'] == 'verified']
        def column(name):
            counts = {}
            for row in rows:
                if row.get(name):
                    counts[row[name]] = counts.get(row[name], 0) + 1
            return [{'value': value, 'count': count} for value, count in sorted(counts.items())]
        coverage = dict(conn.execute("SELECT COUNT(*) monitored, SUM(checked_at IS NOT NULL) analyzed, "
                                     "SUM(status='ok') online FROM stores WHERE enabled=1").fetchone())
        restocks = conn.execute("SELECT COUNT(*) FROM restocks r JOIN deals d ON d.id=r.deal_id "
                                "WHERE r.active=1 AND d.image_status='verified' AND d.page_status='ok' "
                                "AND d.status NOT IN ('rejected','merged')").fetchone()[0]
    return {'mode': 'public', 'read_only': True,
            'market': {key: PROFILE[key] for key in ('country', 'name', 'currency', 'language')},
            'coverage': coverage, 'restocks': restocks, 'stores': column('store'),
            'categories': column('category'), 'subcategories': column('subcategory'),
            'types': column('product_type'),
            'totals': {'deals': len(radar), 'available': len(active),
                       'free': sum(row['price'] == 0 for row in radar),
                       'free_available': sum(row['price'] == 0 for row in active),
                       'extreme': sum((row['discount_pct'] or 0) >= 90 for row in radar)}}


@app.get('/api/deals')
def deals(country: str = '', store: str = '', category: str = '', subcategory: str = '',
          product_type: str = '', q: str = Query('', max_length=300),
          min_discount: float = Query(0, ge=0, le=100), min_score: float = Query(0, ge=0, le=100),
          free_only: int = 0, known_only: int = 0, stock_only: int = 0,
          status: str = 'radar', max_price: float | None = Query(None, ge=0),
          sort: str = 'score', limit: int = Query(200, ge=1, le=500)):
    if status not in {'radar', 'all', 'verified', 'expired', 'stale', 'conditional', 'unverified', 'candidate'}:
        raise HTTPException(422, 'Estado de oferta no válido.')
    filters = locals().copy()
    with readonly_connection() as conn:
        rows = visible(query_deals(conn, hide_samples=True, **filters))
    return {'deals': [public_deal(row) for row in rows]}


@app.get('/api/deals/{key}')
def detail(key: str):
    with readonly_connection() as conn:
        row = conn.execute("SELECT * FROM deals WHERE id=? AND status NOT IN ('rejected','merged') "
                           "AND image_status='verified' AND image LIKE '/static/cache/%'", (key,)).fetchone()
        if not row or not allowed(row['url'], row['country'] == COUNTRY):
            raise HTTPException(404, 'Oferta no encontrada.')
        history = [dict(item) for item in conn.execute(
            'SELECT price,status,checked_at FROM observations WHERE deal_id=? ORDER BY id DESC LIMIT 60', (key,))]
    return {'deal': public_deal(unpack(row)), 'history': history}


@app.get('/api/restocks')
def restocks_view():
    with readonly_connection() as conn:
        rows = [dict(row) for row in conn.execute(
            "SELECT r.url,r.last_checked,r.next_check,r.interval_hours,d.title,d.variant,d.store,"
            "d.price,d.image,d.score,d.free_review,d.free_review_reason,d.review_hold FROM restocks r "
            "JOIN deals d ON d.id=r.deal_id WHERE r.active=1 AND d.image_status='verified' "
            "AND d.page_status='ok' AND d.status NOT IN ('rejected','merged') ORDER BY r.last_checked DESC")]
    for row in rows:
        row['buy_url'] = affiliate_url(row['url'])
        row['free_review_reason'] = ('Pendiente de una revisión adicional de la oferta.'
                                     if row.pop('review_hold', '') else public_text(row.get('free_review_reason')))
    return {'restocks': rows}


@app.get('/api/history')
def historical_examples():
    if COUNTRY != 'ES':
        return {'examples': []}
    examples = []
    rows = json.loads((ROOT / 'catalogs' / 'ES-history.json').read_text(encoding='utf-8'))
    for row in rows:
        # Never read private-history or expose receipt/order screenshots. Reuse
        # only already-cached photographs with a public product-image origin.
        image_url = row.get('image_url') or ''
        if not image_url.startswith(('https://', 'http://')):
            continue
        filename = hashlib.sha256(image_url.encode()).hexdigest() + '.webp'
        if not (IMAGE_DIR / filename).is_file():
            continue
        fields = {'id', 'title', 'store', 'historical_price', 'reference_price', 'reference_note',
                  'variant', 'note', 'date', 'current_price', 'approximate_match'}
        result = {key: row[key] for key in fields if key in row}
        result['status'] = 'historical'
        result['image'] = '/static/cache/' + filename
        result['buy_url'] = affiliate_url(row['url']) if row.get('url') and allowed(row['url']) else ''
        if row.get('reference_price'):
            result['discount_pct'] = round((1-row['historical_price']/row['reference_price'])*100, 1)
        examples.append(result)
    return {'examples': examples}
