"""An accepted AI review survives evidence-note changes, never changed terms."""
import copy
import json
import sqlite3
import unittest
from unittest.mock import patch

from cero import analyzer, db


class PriorAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.conn=sqlite3.connect(':memory:');self.conn.row_factory=sqlite3.Row
        self.conn.executescript(db.BASE)
        for key,kind in db.EXTRA.items():self.conn.execute(f'ALTER TABLE deals ADD COLUMN {key} {kind}')
        self.old={'id':'known','url':'https://tienda.es/products/bolsa?variant=123','title':'Bolsa de papel azul',
            'variant':'Default Title','price':0,'availability':'in_stock','status':'verified','page_status':'ok',
            'verification_level':'cart','image_status':'verified','shipping':4.5,'free_review':'accepted',
            'score_source':'gemini-2.5-flash-lite','ai_score':98,'ai_reason':'Artículo físico independiente sin compra adicional.',
            'score':98,'verdict':'gratis','sale_context':'Bolsa de papel. Dimensiones 33 x 10 x 29 cm.',
            'conditions':'Producto a cero en cesta individual, con tarifa de entrega cotizada.',
            'category':'Accesorios','subcategory':'Embalaje','product_type':'bolsa de papel','checked_at':db.now(),
            'review_hold':'','is_sample':0}
        keys=','.join(self.old)
        self.conn.execute(f'INSERT INTO deals({keys}) VALUES({",".join("?" for _ in self.old)})',list(self.old.values()))
        self.conn.commit()
        self.fresh={key:value for key,value in self.old.items() if key not in {'id','score_source','ai_score','ai_reason','score','free_review'}}
        self.fresh['evidence']=['Nueva comprobación de cesta y nota de transporte.']

    def tearDown(self):self.conn.close()

    def score_with_zero_budget(self,deal):
        messages=[]
        with patch.object(analyzer,'GEMINI_BUDGET_EUR',0),patch.object(analyzer,'GEMINI_API_KEY','test'),patch.object(analyzer.requests,'post') as post:
            analyzer.score_deals(self.conn,[deal],messages.append)
            post.assert_not_called()
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM usage').fetchone()[0],0)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM ai_reservations').fetchone()[0],0)
        return messages

    def test_same_review_reused_at_zero_budget_with_fresh_cart(self):
        fresh=copy.deepcopy(self.fresh)
        fresh['sale_context']='  BOLSA de papel.\nDimensiones 33 x 10 x 29 cm. '
        messages=self.score_with_zero_budget(fresh)
        self.assertEqual(fresh['status'],'verified')
        self.assertEqual(fresh['free_review'],'accepted')
        self.assertEqual(fresh['ai_score'],98)
        self.assertEqual(fresh['ai_reason'],self.old['ai_reason'])
        self.assertEqual(fresh['_assessment_cache'],'prior_accepted_review')
        self.assertEqual(fresh['score_source'],self.old['score_source'])
        self.assertTrue(any('reutilizada' in line for line in messages))

    def test_new_description_or_variant_needs_new_review(self):
        for changed in [{'sale_context':self.old['sale_context']+' Regalo solo con una compra mínima de 50 EUR.'},
                        {'variant':'Azul'}, {'url':'https://tienda.es/products/bolsa?variant=456'},
                        {'title':'Otra bolsa'}, {'shipping':9.5}]:
            with self.subTest(changed=changed):
                fresh={**copy.deepcopy(self.fresh),**changed}
                self.score_with_zero_budget(fresh)
                self.assertEqual(fresh['free_review'],'pending')
                self.assertEqual(fresh['status'],'conditional')
                self.assertNotIn('_assessment_cache',fresh)

    def test_new_condition_cannot_be_hidden_in_cart_note(self):
        fresh=copy.deepcopy(self.fresh)
        fresh['conditions']='Producto a cero en cesta individual. Obligatorio comprar otro producto.'
        self.score_with_zero_budget(fresh)
        self.assertEqual(fresh['free_review'],'pending')

    def test_new_product_is_not_promoted_from_similar_description(self):
        fresh={**copy.deepcopy(self.fresh),'url':'https://tienda.es/products/otra-bolsa?variant=123'}
        self.score_with_zero_budget(fresh)
        self.assertEqual(fresh['free_review'],'pending')

    def test_review_hold_disables_reuse_even_with_same_cart(self):
        self.conn.execute("UPDATE deals SET review_hold='Incidencia comunicada sin resolver'");self.conn.commit()
        fresh=copy.deepcopy(self.fresh)
        self.score_with_zero_budget(fresh)
        self.assertEqual(fresh['free_review'],'pending')
        self.assertEqual(fresh['status'],'conditional')
        self.assertNotIn('_assessment_cache',fresh)

    def test_current_stock_image_page_and_cart_must_be_verified(self):
        for changed in [{'status':'rejected'},{'status':'conditional'},{'availability':'out_of_stock'},
                        {'image_status':'pending'},{'page_status':'not_found'}, {'verification_level':'page'},
                        {'purchase_rejected':True},{'_zero_template':True}]:
            with self.subTest(changed=changed):
                fresh={**copy.deepcopy(self.fresh),**changed}
                self.score_with_zero_budget(fresh)
                self.assertNotEqual(fresh.get('free_review'),'accepted')
                self.assertNotIn('_assessment_cache',fresh)

    def test_missing_original_ai_reason_cannot_invent_a_review(self):
        self.conn.execute("UPDATE deals SET ai_reason=''");self.conn.commit()
        fresh=copy.deepcopy(self.fresh)
        self.score_with_zero_budget(fresh)
        self.assertEqual(fresh['free_review'],'pending')

    def test_exact_ai_cache_keeps_precedence(self):
        fresh=copy.deepcopy(self.fresh)
        fingerprint_deal={**fresh,'status':'conditional','free_review':'pending'}
        result={'score':50,'free_assessment':'uncertain','is_sample':False,'reason':'Nueva condición ambigua.'}
        self.conn.execute('INSERT INTO ai_cache VALUES(?,?,?)',
                          (analyzer.fingerprint(fingerprint_deal),json.dumps(result),db.now()));self.conn.commit()
        self.score_with_zero_budget(fresh)
        self.assertEqual(fresh['free_review'],'uncertain')
        self.assertNotIn('_assessment_cache',fresh)


if __name__=='__main__':unittest.main()
