import unittest
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup

from cero.woocheck import woo_classic_rejection


URL = 'https://tienda.es/producto/enhebrador/'
FORM = '''<form class="cart" action="/producto/enhebrador/" method="post">
<input type="hidden" name="_wpnonce" value="public-token">
<input type="hidden" name="billing_email" value="do-not-send@example.com">
<input name="quantity" value="9"><button name="add-to-cart" value="3179">Añadir</button>
</form>'''


def response(markup='', status=200, headers=None):
    return Mock(status_code=status, text=markup, headers=headers or {})


class WooClassicTests(unittest.TestCase):
    def check(self, markup, form=FORM, session=None):
        session = session or Mock()
        session.post.return_value = response(markup)
        with patch('cero.woocheck.public_url', return_value=True):
            result = woo_classic_rejection(session, {'url': URL, 'price': 0}, BeautifulSoup(form, 'lxml'), 3179)
        return result, session

    def test_explicit_store_rejection_and_no_personal_fields(self):
        result, session = self.check('<ul class="woocommerce-error"><li>Lo siento, este producto no se puede comprar.</li></ul>')
        self.assertTrue(result['purchase_rejected'])
        self.assertFalse(result['item_at_zero'])
        self.assertFalse(result['checkout_submitted'])
        self.assertIn('no se puede comprar', result['evidence'])
        self.assertEqual(session.post.call_args.kwargs['data'], {'_wpnonce': 'public-token', 'add-to-cart': '3179', 'quantity': '1'})

    def test_no_error_never_confirms_free_purchase(self):
        result, _ = self.check('<p>Producto añadido. Precio 0,00 €</p>')
        self.assertIsNone(result)

    def test_external_action_is_not_called(self):
        result, session = self.check('', FORM.replace('/producto/enhebrador/', 'https://otra.es/collect'))
        self.assertIsNone(result)
        session.post.assert_not_called()

    def test_related_product_error_is_ignored(self):
        result, _ = self.check('<section class="related"><p role="alert">Sorry, this product cannot be purchased.</p></section>')
        self.assertIsNone(result)

    def test_related_form_is_not_submitted(self):
        result, session = self.check('', '<section class="related">' + FORM + '</section>')
        self.assertIsNone(result)
        session.post.assert_not_called()

    def test_variation_form_is_not_submitted(self):
        result, session = self.check('', FORM.replace('class="cart"', 'class="cart variations_form"'))
        self.assertIsNone(result)
        session.post.assert_not_called()

    def test_english_rejection_in_product_alert(self):
        result, _ = self.check('<main><div role="alert">Sorry, this product cannot be purchased.</div></main>')
        self.assertTrue(result['purchase_rejected'])

    def test_external_redirect_is_not_followed(self):
        session = Mock()
        session.post.return_value = response(status=302, headers={'Location': 'https://otra.es/checkout'})
        with patch('cero.woocheck.public_url', return_value=True):
            result = woo_classic_rejection(session, {'url': URL, 'price': 0}, BeautifulSoup(FORM, 'lxml'), 3179)
        self.assertIsNone(result)
        session.get.assert_not_called()

    def test_same_host_redirect_can_report_explicit_rejection(self):
        session = Mock()
        session.post.return_value = response(status=302, headers={'Location': '/producto/enhebrador/?notice=1'})
        session.get.return_value = response('<ul class="woocommerce-error">Este producto no se puede comprar.</ul>')
        with patch('cero.woocheck.public_url', return_value=True):
            result = woo_classic_rejection(session, {'url': URL, 'price': 0}, BeautifulSoup(FORM, 'lxml'), 3179)
        self.assertTrue(result['purchase_rejected'])
        session.get.assert_called_once()

    def test_private_redirect_is_not_followed(self):
        session = Mock()
        session.post.return_value = response(status=302, headers={'Location': '/restricted'})
        with patch('cero.woocheck.public_url', side_effect=lambda u: not u.endswith('/restricted')):
            result = woo_classic_rejection(session, {'url': URL, 'price': 0}, BeautifulSoup(FORM, 'lxml'), 3179)
        self.assertIsNone(result)
        session.get.assert_not_called()


if __name__ == '__main__':
    unittest.main()
