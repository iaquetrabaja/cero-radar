"""Tests de regresión para los fallos observados en fichas y listados reales."""
import json
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch,Mock
from bs4 import BeautifulSoup
from cero import db,analyzer
from cero.verification import parse_product
from cero.policy import canonical,affiliate_url,allowed,public_url
from cero.listings import extract_listing
from cero.images import usable,cache_image

URL='https://tienda.es/producto/robot'
IMAGE='https://tienda.es/images/robot.jpg'


def page(price=20,reference=200,availability='InStock',button=True,extra='',offers=None):
    offer={'@type':'Offer','price':price,'priceCurrency':'EUR','availability':'https://schema.org/'+availability,'url':URL}
    if reference:offer['priceSpecification']={'priceType':'https://schema.org/StrikethroughPrice','price':reference}
    product={'@type':'Product','name':'Robot aspirador de prueba','url':URL,'image':IMAGE,'offers':offers or offer}
    return '<html lang="es"><h1>Robot aspirador de prueba</h1><script type="application/ld+json">'+json.dumps(product)+'</script>'+('<form class="cart"><button class="single_add_to_cart_button">Añadir al carrito</button></form>' if button else '')+extra+'</html>'


class ExtractionTests(unittest.TestCase):
    def test_real_discount(self):
        d=parse_product(URL,page())[0]
        self.assertEqual((d['price'],d['reference_price'],d['discount_pct'],d['status']),(20,200,90,'verified'))
    def test_empty_cart_zero_is_not_price(self):
        d=parse_product(URL,page(extra='<aside>Tu carrito: 0,00 EUR</aside>'))[0]
        self.assertEqual(d['price'],20);self.assertFalse(d['is_free'])
    def test_aggregate_not_previous_price(self):
        html=page(offers={'@type':'AggregateOffer','lowPrice':20,'highPrice':200,'priceCurrency':'EUR'})
        self.assertEqual(parse_product(URL,html),[])
    def test_recommendation_does_not_verify_purchase(self):
        d=parse_product(URL,page(button=False,extra='<section class="related"><button>Añadir al carrito</button></section>'))[0]
        self.assertEqual(d['status'],'candidate')
    def test_disabled_button_not_verified(self):
        d=parse_product(URL,page().replace('class="single_add_to_cart_button"','class="single_add_to_cart_button" disabled'))[0]
        self.assertEqual(d['status'],'candidate')
    def test_zero_needs_cart_evidence(self):
        d=parse_product(URL,page(price=0))[0]
        self.assertEqual(d['status'],'candidate');self.assertTrue(d['_cart_eligible'])
    def test_amazon_zero_also_needs_cart(self):
        h='<html><span id="productTitle">Producto de prueba</span><div id="corePrice_feature_div"><span class="a-price"><span class="a-offscreen">0,00 EUR</span></span></div><input id="add-to-cart-button"></html>'
        d=parse_product('https://www.amazon.es/dp/B08VS28Y7F',h)[0]
        self.assertEqual(d['status'],'candidate')
    def test_hidden_form_in_description(self):
        html=page(price=0,extra='<div id="tab-description">form.cart{display:none !important;}</div>')
        d=parse_product(URL,html)[0]
        self.assertEqual(d['status'],'candidate');self.assertNotIn('_cart_eligible',d)
    def test_sample_cannot_be_promoted_by_cart(self):
        d=parse_product(URL,page(price=0).replace('Robot aspirador de prueba','Muestra de crema'))[0]
        self.assertEqual(d['status'],'rejected');self.assertNotIn('_cart_eligible',d)
    def test_return_service_is_not_a_free_product(self):
        d=parse_product(URL,page(price=0).replace('Robot aspirador de prueba','Cambio de caja retornable (recoger la anterior)'))[0]
        self.assertEqual(d['status'],'rejected');self.assertNotIn('_cart_eligible',d)
    def test_out_of_stock_retained(self):
        d=parse_product(URL,page(price=0,availability='OutOfStock'))[0]
        self.assertEqual(d['status'],'expired');self.assertEqual(d['price'],0)
    def test_related_product_wrong_url_ignored(self):
        other={'@type':'Product','name':'Robot aspirador de prueba','url':'https://tienda.es/otro','offers':{'@type':'Offer','price':0,'priceCurrency':'EUR'}}
        html=page()+f'<script type="application/ld+json">{json.dumps(other)}</script>'
        self.assertEqual([d['price'] for d in parse_product(URL,html)],[20])
    def test_xml_encoding_is_supported(self):
        self.assertEqual(parse_product(URL,'<?xml version="1.0" encoding="UTF-8"?>'+page())[0]['price'],20)
    def test_product_image_placeholder_not_accepted(self):
        self.assertFalse(usable('https://tienda.es/woocommerce-placeholder.png'))
        self.assertFalse(usable('https://tienda.es/logo.png'))
        self.assertTrue(usable(IMAGE))
    def test_amazon_empty_offscreen_and_reference_same_block(self):
        h='''<html><span id="productTitle">Auriculares de prueba</span><div id="corePrice_feature_div"><span class="a-price"><span class="a-offscreen">10,70 EUR</span></span></div><div id="corePriceDisplay_desktop_feature_div"><span id="apex-pricetopay-accessibility-label">10,70 EUR con ahorro del 84%</span><span class="a-price"><span class="a-offscreen"></span></span><span class="a-text-price"><span class="a-offscreen">64,90 EUR</span></span></div><input id="add-to-cart-button"><div id="availability">En stock</div></html>'''
        d=parse_product('https://www.amazon.es/dp/B08VS28Y7F',h)[0]
        self.assertEqual((d['price'],d['reference_price'],d['status']),(10.7,64.9,'verified'))
    def test_amazon_inline_twister_selected_size(self):
        h='''<span id="productTitle">Vaqueros</span><div id="corePrice_feature_div"><span class="a-price"><span class="a-offscreen">23,33 EUR</span></span><span class="a-text-price"><span class="a-offscreen">149,90 EUR</span></span></div><input id="add-to-cart-button"><div id="inline-twister-expander-content-size_name"><li data-initiallyselected="false"><span class="swatch-title-text">25W / 28L</span></li><li data-initiallyselected="true"><span class="swatch-title-text">26W / 28L</span></li></div>'''
        d=parse_product('https://www.amazon.es/dp/B0F4QL2DJS',h)[0]
        self.assertEqual(d['variant'],'Talla 26W / 28L');self.assertEqual(d['discount_pct'],84.4)
    def test_listing_does_not_invent_product_at_page_url(self):
        html='<html><h1>Ofertas de la tienda</h1><button>Añadir al carrito</button>0,00 EUR 900,00 EUR</html>'
        self.assertEqual(extract_listing(html,'https://tienda.es/','Tienda',''),[])


class AmazonDiscoveryTests(unittest.TestCase):
    def test_access_challenge_is_not_empty_search(self):
        from cero.http import _blocked
        self.assertTrue(_blocked(200,'<html><script>function triggerInterstitialChallenge(){}</script></html>'))
    def test_listing_filter_never_invents_reference(self):
        from cero.amazon import parse_results
        h='''<div data-component-type="s-search-result" data-asin="B0F4QL2DJS"><h2>Vaqueros de prueba</h2><span class="a-price"><span class="a-offscreen">23,33 EUR</span></span><span>90% algodón</span></div>'''
        d=parse_results(h,'80%+')[0]
        self.assertIsNone(d['reference_price']);self.assertIsNone(d['discount_pct']);self.assertEqual(d['_amazon_badge'],0)
    def test_reference_label_and_discount_badge(self):
        from cero.amazon import parse_results
        h='''<div data-component-type="s-search-result" data-asin="B0F4QL2DJS"><h2>Vaqueros de prueba</h2><span class="a-price"><span class="a-offscreen">23,33 EUR</span></span><span>Recomendado: 149,90 €</span><span>Ahorra 84%</span></div>'''
        d=parse_results(h,'prueba')[0]
        self.assertEqual(d['reference_price'],149.9);self.assertEqual(d['discount_pct'],84.4);self.assertEqual(d['_amazon_badge'],84)
    def test_rotation_reaches_second_page_and_ninety_percent(self):
        from cero.amazon import search_jobs
        from urllib.parse import urlparse,parse_qs
        state={};visits={}
        for _ in range(36):
            jobs,state=search_jobs(state)
            for name,url in jobs:
                q=parse_qs(urlparse(url).query)
                key=q.get('k',q.get('i'))[0];visits.setdefault(key,[]).append(q)
        rows=visits['Tommy Hilfiger']
        self.assertEqual([q['page'][0] for q in rows[:5]],['1','2','3','4','1'])
        self.assertEqual(rows[4]['rh'],['p_8:90-'])


class PolicyTests(unittest.TestCase):
    def test_product_sku_fragment_survives(self):
        u='https://tienda.es/p#/sku/189168'
        self.assertEqual(canonical(u),u)
    def test_amazon_tag_outgoing_only(self):
        u='https://www.amazon.es/dp/B08VS28Y7F?tag=otro-21&ref=x'
        self.assertEqual(canonical(u),'https://www.amazon.es/dp/B08VS28Y7F')
        with patch('cero.config.AMAZON_ASSOCIATE_TAG','test-21'):
            self.assertTrue(affiliate_url(u).endswith('?tag=test-21'))
    def test_no_affiliation_in_other_shop(self):
        self.assertEqual(affiliate_url(URL),URL)
    def test_foreign_and_secondhand_excluded(self):
        for u in ('https://amazon.it/dp/X','https://shop.de/p','https://milanuncios.com/p','http://127.0.0.1/x'):
            self.assertFalse(allowed(u,True),u)
    def test_private_network_rejected(self):
        with patch('cero.policy.socket.getaddrinfo',return_value=[(2,1,6,'',('192.168.1.1',443))]):
            self.assertFalse(public_url('https://tienda.es/x'))
    def test_ai_cannot_turn_positive_price_free(self):
        d={'price':20,'is_free':False,'status':'candidate'}
        analyzer._apply(d,{'score':100,'verdict':'gratis','is_free':True})
        self.assertEqual(d['price'],20);self.assertFalse(d['is_free']);self.assertEqual(d['status'],'candidate');self.assertLessEqual(d['score'],40)
    def test_confirmed_zero_interest_is_not_low_because_shipping_unknown(self):
        d={'price':0,'status':'verified','verification_level':'cart','delivery_status':'shipping_required'}
        analyzer._apply(d,{'score':10,'reason':'Gastos desconocidos'})
        self.assertEqual(d['ai_score'],10);self.assertEqual(d['score'],96)
        self.assertTrue(d['score_source'].startswith('priority+'))


class ClassificationTests(unittest.TestCase):
    def test_cycling_parts_not_bicycles(self):
        from cero.taxonomy import classify
        for title,kind in [('Calas DPV 9º rojo','calas'),('Sillín Selle SMP E-Bike Large','sillín'),('Pastillas de freno SpeedSix CarbonStop','frenos de bicicleta')]:
            self.assertEqual(classify(title),{'category':'Deporte','subcategory':'Ciclismo','product_type':kind})
    def test_headset_not_other(self):
        from cero.taxonomy import classify
        self.assertEqual(classify('Energy Sistem Gaming Headset ESG 6 True Wireless')['category'],'Tecnología')
    def test_origin_sku_not_orderable_is_not_free_available(self):
        u='https://tienda.es/product/lotion#/sku/1'
        raw={'catalog-spp':{'PRODUCT_ID':'PROD1','url':'/product/lotion','PROD_RGN_NAME':'Ginger','skus':[{'SKU_BASE_ID':1,'PRICE':0,'isOrderable':0,'isShoppable':0,'isOutOfStock':0},{'SKU_BASE_ID':2,'PRICE':20,'isOrderable':1,'isShoppable':1}]}}
        h='<html lang="es"><script id="page_data" type="application/json">'+json.dumps(raw)+'</script></html>'
        d=parse_product(u,h)
        self.assertEqual(len(d),1);self.assertEqual(d[0]['price'],0);self.assertEqual(d[0]['status'],'conditional')


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.original=db.DB_PATH;db.DB_PATH=Path(self.tmp.name)/'test.db';self.c=db.connect()
    def tearDown(self):
        self.c.close();db.DB_PATH=self.original;self.tmp.cleanup()
    def put(self,**extra):
        d={'url':URL,'title':'Robot aspirador de prueba','price':0,'availability':'out_of_stock','status':'expired','page_status':'ok','image':'/static/cache/'+'a'*64+'.webp','image_status':'verified'};d.update(extra);db.upsert(self.c,d);self.c.commit()
    def test_zero_out_of_stock_due_in_twelve_hours(self):
        self.put();r=self.c.execute('SELECT * FROM restocks').fetchone()
        self.assertEqual((datetime.fromisoformat(r['next_check'])-datetime.fromisoformat(r['last_checked'])).total_seconds(),43200)
    def test_restock_in_stock_deactivates_watch(self):
        self.put();self.put(availability='in_stock',status='verified')
        self.assertEqual(self.c.execute('SELECT active FROM restocks').fetchone()[0],0)
    def test_same_product_price_change_keeps_identity(self):
        self.put();self.put(price=5)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM deals').fetchone()[0],1)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM observations').fetchone()[0],2)
    def test_completing_amazon_size_keeps_same_asin(self):
        self.put(url='https://www.amazon.es/dp/B0F4QL2DJS',variant='')
        self.put(url='https://www.amazon.es/dp/B0F4QL2DJS',variant='Talla 26W / 28L')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM deals').fetchone()[0],1)
        self.assertEqual(self.c.execute('SELECT variant FROM deals').fetchone()[0],'Talla 26W / 28L')
    def test_amazon_explores_missing_list_reference_without_inventing_it(self):
        from cero.amazon import collect
        h='''<div data-component-type="s-search-result" data-asin="B0F4QL2DJS"><h2>Vaqueros de prueba</h2><span class="a-price"><span class="a-offscreen">23,33 EUR</span></span></div>'''
        with patch('cero.amazon.http.get',return_value=(200,h,'https://www.amazon.es/s')),patch('cero.amazon.health'):
            rows,read=collect()
        self.assertEqual(read,1);self.assertEqual(len(rows),1)
        self.assertIsNone(rows[0]['reference_price']);self.assertIsNone(rows[0]['discount_pct'])
    def test_previously_verified_zero_survives_new_uncertainty(self):
        self.put(status='verified',availability='in_stock')
        self.put(status='conditional',availability='in_stock')
        self.assertEqual(len(db.query_deals(self.c,status='radar')),1)
        self.assertEqual(db.query_deals(self.c,status='verified'),[])
    def test_eighty_percent_floor(self):
        self.put(price=25,reference_price=100,discount_pct=75,status='verified')
        self.assertEqual(db.query_deals(self.c,status='verified'),[])
    def test_image_is_required(self):
        self.put(status='verified',availability='in_stock',image_status='missing',image='')
        self.assertEqual(db.query_deals(self.c,status='verified'),[])
    def test_broken_link_is_not_restock(self):
        self.put();self.put(page_status='not_found',availability='unknown',status='expired')
        self.assertEqual(self.c.execute('SELECT active FROM restocks').fetchone()[0],0)
    def test_catalog_zero_without_product_page_does_not_create_restock(self):
        self.put(status='unverified',page_status='unreadable')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM restocks').fetchone()[0],0)
    def test_hidden_sale_is_not_restock(self):
        self.put();self.put(page_status='unavailable')
        self.assertEqual(self.c.execute('SELECT active FROM restocks').fetchone()[0],0)
    def test_budget_only_charges_current_day(self):
        start,end=db.budget_window()
        yesterday=(datetime.fromisoformat(start)-timedelta(seconds=1)).isoformat(timespec='seconds')
        for cost,at in [(2.9,yesterday),(.1,db.now())]:db.add_usage(self.c,'test',1,1,cost);self.c.execute('UPDATE usage SET created_at=? WHERE id=last_insert_rowid()',(at,))
        self.assertAlmostEqual(db.spent_eur(self.c),.1)
    def test_budget_dst_day(self):
        start,end=db.budget_window(datetime(2026,10,25,12,tzinfo=timezone.utc))
        self.assertEqual((datetime.fromisoformat(end)-datetime.fromisoformat(start)).total_seconds(),25*3600)
    def test_stale_does_not_look_active(self):
        old=(datetime.now(timezone.utc)-timedelta(hours=3)).isoformat(timespec='seconds')
        self.put(status='verified',availability='in_stock',checked_at=old)
        self.assertEqual(db.query_deals(self.c,status='verified'),[])
    def test_zero_out_of_stock_is_also_in_radar(self):
        self.put()
        rows=db.query_deals(self.c,status='radar')
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['availability'],'out_of_stock')
    def test_interesting_offer_stays_after_read_failure(self):
        self.put(price=20,reference_price=200,discount_pct=90,status='verified',availability='in_stock')
        self.put(price=20,reference_price=200,discount_pct=90,status='blocked',availability='unknown',page_status='unreadable')
        self.assertEqual(len(db.query_deals(self.c,status='radar')),1)
    def test_ended_discount_keeps_best_observation(self):
        self.put(price=20,reference_price=200,discount_pct=90,status='verified',availability='in_stock')
        self.put(price=150,reference_price=200,discount_pct=25,status='verified',availability='in_stock')
        rows=db.query_deals(self.c,status='radar')
        self.assertEqual(rows[0]['best_price'],20);self.assertEqual(rows[0]['status'],'ended')
        self.assertEqual(db.query_deals(self.c,status='verified'),[])
    def test_alert_queue_rearms_only_when_price_improves(self):
        from cero.telegram import enqueue
        self.put(price=20,reference_price=200,discount_pct=90,status='verified',availability='in_stock',score=90)
        row=db.unpack(self.c.execute('SELECT * FROM deals').fetchone());enqueue(self.c,row['id'],row)
        self.c.execute('UPDATE notifications SET sent_at=?',(db.now(),));self.c.commit()
        enqueue(self.c,row['id'],row)
        self.assertIsNotNone(self.c.execute('SELECT sent_at FROM notifications').fetchone()[0])
        row['price']=0;enqueue(self.c,row['id'],row)
        self.assertIsNone(self.c.execute('SELECT sent_at FROM notifications').fetchone()[0])
    def test_telegram_remains_disabled(self):
        from cero import telegram
        with patch.dict('os.environ',{'TELEGRAM_ENABLED':'false'}):
            self.assertFalse(telegram.armed());self.assertFalse(telegram.send_deal({'price':0}))
    def test_budget_reserved_before_request(self):
        self.c.execute('INSERT INTO usage(model,est_eur,created_at) VALUES(?,?,?)',('test',.79,db.now()));self.c.commit()
        with patch.object(analyzer,'GEMINI_BUDGET_EUR',.8),patch.object(analyzer,'GEMINI_API_KEY','test'),patch.object(analyzer.requests,'post') as post:
            analyzer.score_deals(self.c,[{'price':0,'status':'candidate'}],lambda s:None)
            post.assert_not_called()

if __name__=='__main__':unittest.main()
