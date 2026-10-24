import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from cero.shopifycheck import inspect


class ShopifyVariantIdentityTests(unittest.TestCase):
    def test_form_selected_variant_is_added_to_product_url(self):
        deal={'url':'https://tienda.es/products/bolsa?campaign=oferta+especial&empty=',
              'price':0,'availability':'in_stock','status':'candidate'}
        soup=BeautifulSoup('<form action="/cart/add"><input name="id" value="123"></form>','lxml')
        product={'title':'Bolsa','images':['/bolsa.jpg'],'variants':[{'id':123,'price':0,'available':True}]}
        with patch('cero.shopifycheck.http.get',return_value=(200,json.dumps(product),'')):
            inspect(deal,soup)
        parsed=urlparse(deal['url'])
        self.assertEqual(parsed.path,'/products/bolsa')
        self.assertEqual(parse_qs(parsed.query,keep_blank_values=True),
                         {'campaign':['oferta especial'],'empty':[''],'variant':['123']})

    def test_missing_catalog_variant_does_not_change_url(self):
        url='https://tienda.es/products/bolsa?campaign=oferta'
        deal={'url':url,'price':0,'status':'candidate'}
        soup=BeautifulSoup('<form action="/cart/add"><input name="id" value="999"></form>','lxml')
        product={'variants':[{'id':123,'price':0,'available':True}]}
        with patch('cero.shopifycheck.http.get',return_value=(200,json.dumps(product),'')):
            inspect(deal,soup)
        self.assertEqual(deal['url'],url)
        self.assertEqual(deal['availability'],'unknown')

    def test_explicit_url_variant_takes_precedence_over_form(self):
        deal={'url':'https://tienda.es/products/bolsa?variant=456&campaign=a',
              'price':0,'availability':'in_stock','status':'candidate'}
        soup=BeautifulSoup('<form action="/cart/add"><input name="id" value="123"></form>','lxml')
        product={'images':['/bolsa.jpg'],'variants':[{'id':456,'price':0,'available':False}]}
        with patch('cero.shopifycheck.http.get',return_value=(200,json.dumps(product),'')):
            inspect(deal,soup)
        self.assertEqual(parse_qs(urlparse(deal['url']).query),{'variant':['456'],'campaign':['a']})
        self.assertEqual(deal['availability'],'out_of_stock')


if __name__=='__main__':
    unittest.main()
