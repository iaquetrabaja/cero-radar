"""Tests de regresión para los fallos observados en fichas y listados reales."""
import json
import html
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
    def test_historical_cases_are_never_live_deals(self):
        from cero.history import examples,evidence_path
        with patch('cero.history.cache_image',return_value='/static/cache/'+'a'*64+'.webp'):
            rows=examples()
        self.assertEqual(len(rows),11);self.assertTrue(all(d['status']=='historical' for d in rows))
        robot=next(d for d in rows if d['id']=='conga-q200-xtreme')
        self.assertEqual((robot['historical_price'],robot['reference_price']),(22.9,399))
        self.assertIsNone(evidence_path('../../.env'))
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


class ShopifyVariantTests(unittest.TestCase):
    def test_stock_overrules_hidden_html_cart_form(self):
        from cero.shopifycheck import apply_variant
        d={'price':0,'status':'verified','availability':'in_stock','image':IMAGE,'_cart_eligible':True}
        apply_variant(d,{'images':[],'variants':[{'id':123,'price':0,'available':False,'title':'40'}]},'123')
        self.assertEqual(d['status'],'expired');self.assertEqual(d['availability'],'out_of_stock')
        self.assertNotIn('_cart_eligible',d);self.assertEqual(d['image_status'],'missing');self.assertEqual(d['variant'],'40')
    def test_other_size_cannot_confirm_selected_size(self):
        from cero.shopifycheck import apply_variant
        d={'price':0,'status':'candidate','_cart_eligible':True}
        apply_variant(d,{'variants':[{'id':124,'price':0,'available':True}]},'123')
        self.assertEqual(d['status'],'unverified');self.assertNotIn('_cart_eligible',d)


class CommunityTests(unittest.TestCase):
    def test_zero_price_shipping_and_digital_posts_are_not_product_leads(self):
        from cero.signals import listing
        def article(title,host):
            return '<article><div data-vue3="'+html.escape(json.dumps({'props':{'thread':{'threadId':'1','title':title,'linkHost':host,'price':0,'type':'Deal','merchant':{'merchantName':'Tienda'}}}},ensure_ascii=False),quote=True)+'"></div><a class="thread-link" href="https://www.chollometro.com/ofertas/1">Ver</a></article>'
        h=article('Dos fundas para tablet a cero','www.mi.com')+article('Envío gratis en toda la web','tienda.es')+article('Juego gratis free to play','store.steampowered.com')
        rows=listing(h);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['status'],'lead');self.assertNotEqual(rows[0].get('verification_level'),'cart')


class FrontierTests(unittest.TestCase):
    def test_catalog_cents_and_discount_only_find_candidates(self):
        from cero.frontier import catalog_rows
        payload=[{'name':'Robot','permalink':URL,'prices':{'price':'1999','regular_price':'39900','currency_minor_unit':2,'currency_code':'EUR'},'is_in_stock':True},
                 {'name':'Archivo','permalink':URL+'/archivo','is_virtual':True,'prices':{'price':'0'}}]
        rows,read=catalog_rows(payload,'tienda.es','WooCommerce')
        self.assertEqual(read,2);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['price'],19.99)
        self.assertGreater(rows[0]['discount_pct'],90);self.assertNotEqual(rows[0].get('status'),'verified')
    def test_woocommerce_probes_zero_and_positive_sales_separately(self):
        from cero.frontier import catalog_probe
        with patch('cero.frontier.http.get',return_value=(200,'[]','https://tienda.es/')),patch('cero.frontier.health'):
            with patch('cero.frontier.http.get',return_value=(200,'[]','https://tienda.es/')) as get:
                catalog_probe({'domain':'tienda.es','platform':'WooCommerce','url':'https://tienda.es'},3)
                urls=[call.args[0] for call in get.call_args_list]
        self.assertEqual(len(urls),2);self.assertIn('max_price=0',urls[0]);self.assertIn('on_sale=true&page=3',urls[1]);self.assertNotIn('max_price=0',urls[1])


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
        analyzer._apply(d,{'score':10,'reason':'Gastos desconocidos','free_assessment':'accepted'})
        self.assertEqual(d['ai_score'],10);self.assertEqual(d['score'],96)
        self.assertTrue(d['score_source'].startswith('priority+'))


class FreeReviewTests(unittest.TestCase):
    def test_phone_sale_rejected_before_cart(self):
        from cero.freecheck import inspect
        d={'title':'Escáner Spectrum','price':0,'url':URL,'status':'candidate','evidence':[],'_cart_eligible':True}
        inspect(d,BeautifulSoup('<main><div class="summary">ÚNICAMENTE VENTA TELEFÓNICA. ATENCIÓN AL 677653291</div></main>','lxml'))
        self.assertEqual(d['status'],'rejected');self.assertNotIn('_cart_eligible',d)
        self.assertIn('VENTA TELEFÓNICA',d['sale_context'])
    def test_dummy_product_rejected_even_without_stock(self):
        from cero.freecheck import inspect
        d={'title':'PRUEBA5-','price':0,'url':'https://farmaciasantaursula.es/prueba5/','status':'expired','availability':'out_of_stock','evidence':[]}
        inspect(d,BeautifulSoup('<main>PRUEBA5- 0,00 € Sin existencias</main>','lxml'))
        self.assertEqual(d['status'],'rejected')
    def test_phone_contact_alone_does_not_reject(self):
        from cero.freecheck import inspect
        d={'title':'Robot aspirador','price':0,'url':URL,'status':'candidate'}
        inspect(d,BeautifulSoup('<div class="summary">Producto gratuito. Atención telefónica 677653291</div>','lxml'))
        self.assertEqual(d['status'],'candidate')
    def test_condition_is_supplied_to_gemini_without_related_products(self):
        from cero.freecheck import inspect
        d={'title':'Bolsa','url':URL,'price':0}
        inspect(d,BeautifulSoup('<div class="summary">Regalo al comprar dos cremas</div><section class="related">Venta telefónica de otro producto</section>','lxml'))
        prompt=analyzer._prompt([d])
        self.assertIn('Regalo al comprar dos cremas',prompt);self.assertNotIn('Venta telefónica de otro producto',prompt)
    def test_ai_veto_overrules_cart_and_priority_floor(self):
        d={'price':0,'status':'verified','verification_level':'cart','delivery_status':'shipping_required','availability':'in_stock','sale_context':'Regalo al comprar dos cremas'}
        analyzer._apply(d,{'score':98,'free_assessment':'rejected','exclusion_type':'conditional_purchase','exclusion_quote':'Regalo al comprar dos cremas','reason':'Regalo condicionado a comprar otro producto'})
        self.assertEqual(d['status'],'rejected');self.assertEqual(d['score'],0)
    def test_missing_ai_assessment_never_confirms_free(self):
        d={'price':0,'status':'verified','verification_level':'cart','delivery_status':'shipping_required'}
        analyzer._apply(d,{'score':100,'verdict':'gratis'})
        self.assertEqual(d['status'],'conditional');self.assertLessEqual(d['score'],40)
    def test_ai_cannot_promote_missing_cart_or_stock(self):
        d={'price':0,'status':'expired','availability':'out_of_stock','page_status':'ok','verification_level':'page'}
        analyzer._apply(d,{'score':100,'free_assessment':'accepted'})
        self.assertEqual(d['status'],'expired');self.assertEqual(d['verdict'],'vigilar')
    def test_accepted_review_does_not_override_hard_rejection(self):
        d={'price':0,'status':'rejected','verification_level':'cart'}
        analyzer._apply(d,{'score':100,'free_assessment':'accepted'})
        self.assertEqual(d['status'],'rejected');self.assertEqual(d['score'],0)
    def test_ai_cannot_discard_zero_merely_because_stock_is_missing(self):
        d={'price':0,'status':'expired','availability':'out_of_stock','page_status':'ok','sale_context':'Sin existencias'}
        analyzer._apply(d,{'score':0,'free_assessment':'rejected','exclusion_type':'placeholder','exclusion_quote':'Sin existencias','reason':'Está agotado'})
        self.assertEqual(d['status'],'expired');self.assertEqual(d['free_review'],'uncertain')
    def test_shipping_threshold_is_not_a_purchase_requirement(self):
        d={'sale_context':'Envío gratis por compras superiores a 60€'}
        self.assertFalse(analyzer._grounded_exclusion(d,{'exclusion_type':'conditional_purchase','exclusion_quote':'Envío gratis por compras superiores a 60€'}))
    def test_template_page_is_not_confirmed_even_if_ai_accepts(self):
        from cero.freecheck import inspect
        d={'title':'Flor 003','price':0,'url':URL,'status':'verified','verification_level':'cart'}
        inspect(d,BeautifulSoup('<div class="summary">Texto descriptivo. Lorem ipsum dolor sit amet.</div>','lxml'))
        analyzer._apply(d,{'score':100,'free_assessment':'accepted'})
        self.assertEqual(d['status'],'conditional');self.assertEqual(d['free_review'],'uncertain')


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
        d={'url':URL,'title':'Robot aspirador de prueba','price':0,'availability':'out_of_stock','status':'expired','page_status':'ok','image':'/static/cache/'+'a'*64+'.webp','image_status':'verified','free_review':'accepted'};d.update(extra);db.upsert(self.c,d);self.c.commit()
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
    def test_zero_cannot_be_persisted_verified_without_ai_review(self):
        self.put(status='verified',availability='in_stock',free_review='pending')
        r=self.c.execute('SELECT * FROM deals').fetchone()
        self.assertEqual(r['status'],'conditional');self.assertEqual(db.query_deals(self.c,status='verified'),[])
    def test_zero_notification_requires_accepted_review(self):
        from cero.telegram import enqueue
        self.put(status='verified',availability='in_stock')
        d=db.unpack(self.c.execute('SELECT * FROM deals').fetchone());d['free_review']='uncertain'
        enqueue(self.c,d['id'],d);self.assertEqual(self.c.execute('SELECT COUNT(*) FROM notifications').fetchone()[0],0)
    def test_shopify_variant_size_completion_keeps_identity(self):
        self.put(url='https://tienda.es/products/zapato?variant=123',variant='')
        self.put(url='https://tienda.es/products/zapato?variant=123',variant='40')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM deals').fetchone()[0],1)
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
