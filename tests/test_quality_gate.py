import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from decimal import Decimal

from collector.contracts import CollectionBlocked, ListingPage
from collector import quality_gate as gate
from collector.quality_store import health_update, central_section, update_health_cell, reserve_budget
from collector.recon import valid_gtin

EAN='4006381333931'
URL='https://shop.example/products/own?variant=123'
ROW={'url':URL,'price':'25.00','currency':'EUR','title':'Artist - Album LP',
     'product_type':'vinyl','condition':'new','identifier_raw':EAN}

def html(price='25.00', currency='EUR', code=EAN, url=URL, used=False):
    data={'@type':'Product','url':url,'name':'Album LP','gtin13':code,
          'offers':{'@type':'Offer','url':url,'price':price,'priceCurrency':currency}}
    if used:data['itemCondition']='https://schema.org/UsedCondition'
    return '<script type="application/ld+json">'+json.dumps(data)+'</script>'


class QualityTests(unittest.TestCase):
    def test_known_checkdigits_for_all_supported_lengths(self):
        for code in [EAN,'8719262047020','012345678905','04006381333931']:
            self.assertTrue(valid_gtin(code),code)
            self.assertFalse(valid_gtin(code[:-1]+str((int(code[-1])+1)%10)),code)

    def test_same_product_variant_price_currency_and_gtin(self):
        self.assertEqual(gate.detail_evidence(html(),ROW),{EAN.zfill(14)})
        for body in [html(price='4.95'),html(currency='USD'),html(url=URL.replace('123','999')),
                     html(url='https://shop.example/products/related?variant=123'),
                     html(code=EAN[:-1]+'2'),html(used=True), html(price='NaN')]:
            with self.assertRaises(CollectionBlocked):gate.detail_evidence(body,ROW)

    def test_organisation_shipping_offers_cannot_prove_product_price(self):
        body='<script type="application/ld+json">'+json.dumps({'@type':'Organization',
            'url':URL,'offers':{'price':'25.00','priceCurrency':'EUR'}})+'</script>'
        with self.assertRaises(CollectionBlocked):gate.detail_evidence(body,ROW)

    def test_conflicting_product_gtins_fail_closed(self):
        with self.assertRaises(CollectionBlocked):gate.detail_evidence(html()+html(code='8719262047020'),ROW)

    def test_graph_scoped_product_supported(self):
        product=json.loads(html().split('>',1)[1].split('</script>')[0])
        body='<script type="application/ld+json">'+json.dumps({'@graph':[product]})+'</script>'
        self.assertEqual(gate.detail_evidence(body,ROW),{EAN.zfill(14)})

    def validate(self, body, rows=None):
        class Scraper:
            def parse_listing(self,*args,**kwargs):return ListingPage(tuple(rows or [ROW]),None)
            def parse_detail(self,*args,**kwargs):return {'identifier_raw':EAN}
        class Transport:
            def __init__(self,*args,**kwargs):pass
            def get(self,url):return body
        with patch.dict(os.environ,{},clear=True), patch.object(gate,'load_profile',return_value=({'domain':'shop.example','catalog_route':URL},Scraper())):
            return gate.validate(Path('unused'),transport_factory=Transport)

    def test_full_quality_gate_accepts_independently_matched_data(self):
        result=self.validate(html())
        self.assertEqual(result['status'],'APPROVED')
        self.assertEqual(result['valid_eans'],1)
        self.assertFalse(result['database_write'])
        self.assertEqual(len(result['requests']),2)

    def test_wrong_currency_is_review_not_approved(self):
        result=self.validate(html(currency='USD'))
        self.assertEqual(result['status'],'REVIEW')
        self.assertIn('currency',result['reason'])

    def test_missing_identifier_does_not_become_approved(self):
        result=self.validate(html(code=None))
        self.assertEqual(result['status'],'REVIEW')

    def test_used_listing_rejected_even_when_detail_looks_new(self):
        self.assertEqual(self.validate(html(),[{**ROW,'condition':'used'}])['status'],'REVIEW')

    def profiles(self,root):
        profiles=root/'profiles';profiles.mkdir()
        for name in ['a','b']:
            (profiles/f'{name}.json').write_text(json.dumps({'domain':f'{name}.example','platform':'shopify',
                'catalog_route':f'https://{name}.example/products.json','method_candidates':[]}))
            (profiles/f'{name}.py').write_text('# test wrapper\n')
        return profiles

    def test_resume_repair_limit_freeze_and_copy_without_starving_next(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{},clear=True):
            root=Path(tmp);profiles=self.profiles(root);state=root/'quality'
            failing=lambda path,**kw:{'status':'REVIEW','reason':'detail_ean_not_proven'}
            for batch in range(5):gate.run_batch(profiles,state,limit=1,validator=failing)
            saved=json.loads((state/'state.json').read_text())
            self.assertEqual(saved['shops']['a']['status'],'FROZEN')
            self.assertEqual(saved['shops']['a']['repair_attempts'],3)
            self.assertTrue((state/'frozen/a/a.py').exists())
            result=gate.run_batch(profiles,state,limit=1,validator=failing)
            self.assertEqual(result['processed'][0]['slug'],'b')

    def test_approved_exact_release_only_and_two_failures_remove_schedule(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{},clear=True):
            root=Path(tmp);profiles=self.profiles(root);state=root/'quality'
            passed=lambda path,**kw:{'status':'APPROVED','valid_eans':1,'detail_checked':1}
            gate.run_batch(profiles,state,limit=1,validator=passed)
            self.assertEqual(gate.approved(state,profiles),['a'])
            health=state/'health/price/a.json';value=json.loads(health.read_text())
            value['status']='REPAIR_REQUIRED';health.write_text(json.dumps(value))
            self.assertEqual(gate.approved(state,profiles),[])
            self.assertEqual(gate.approved(state,profiles,mode='price'),[])
            self.assertEqual(gate.approved(state,profiles,mode='ean'),['a'])
            value['status']='ACTIVE';health.write_text(json.dumps(value))
            (profiles/'a.py').write_text('# changed release')
            self.assertEqual(gate.approved(state,profiles),[])

    def test_frozen_ean_maintenance_does_not_stop_healthy_price_lane(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{},clear=True):
            root=Path(tmp); profiles=self.profiles(root); state=root/'quality'
            passed=lambda path,**kw:{'status':'APPROVED','valid_eans':1,'detail_checked':1}
            failed=lambda path,**kw:{'status':'REVIEW','reason':'detail_ean_not_proven'}
            gate.run_batch(profiles,state,limit=1,validator=passed)
            p=state/'health/ean/a.json'; health=json.loads(p.read_text())
            health['status']='REPAIR_REQUIRED'; p.write_text(json.dumps(health))
            for _ in range(3): gate.run_batch(profiles,state,limit=1,validator=failed)
            self.assertEqual(json.loads(p.read_text())['status'],'FROZEN')
            self.assertEqual(gate.approved(state,profiles,mode='price'),['a'])
            self.assertEqual(gate.approved(state,profiles,mode='ean'),[])

    def test_403_is_blocked_and_not_repeated_next_batch(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{},clear=True):
            root=Path(tmp);profiles=self.profiles(root);state=root/'quality'
            blocked=lambda path,**kw:{'status':'BLOCKED','reason':'HTTP_403'}
            gate.run_batch(profiles,state,limit=1,validator=blocked)
            second=gate.run_batch(profiles,state,limit=1,validator=blocked)
            self.assertEqual(second['processed'][0]['slug'],'b')

    def test_first_failure_allowed_second_requires_repair_and_duplicate_is_idempotent(self):
        bad={'status':'failure','records':0}
        a=health_update({},bad,mode='ean',run_id='1',observed_at='2026-10-18T01:00')
        self.assertEqual(a['status'],'INCIDENT')
        self.assertEqual(health_update(a,bad,mode='ean',run_id='1',observed_at='2026-10-18T01:00'),a)
        b=health_update(a,bad,mode='ean',run_id='2',observed_at='2026-10-18T02:00')
        self.assertEqual(b['status'],'REPAIR_REQUIRED')
        good={'status':'success','records':20,'ean_records':10,'detail_errors':0}
        c=health_update(b,good,mode='ean',run_id='3',observed_at='2026-10-18T03:00')
        self.assertEqual(c['status'],'ACTIVE')
        self.assertEqual(c['consecutive_failures'],0)

    def test_cap_is_not_failure_but_missing_ean_and_wrong_price_are(self):
        good={'status':'success','records':250,'ean_records':250,'detail_errors':0,'truncated':True}
        self.assertEqual(health_update({},good,mode='ean',run_id='1',observed_at='1')['status'],'ACTIVE')
        self.assertEqual(health_update({},dict(good,detail_errors=1),mode='ean',run_id='1',observed_at='1')['status'],'INCIDENT')
        self.assertEqual(health_update({},dict(good,ean_records=0),mode='ean',run_id='1',observed_at='1')['status'],'INCIDENT')
        self.assertEqual(health_update({},good,mode='price',run_id='1',observed_at='1')['status'],'INCIDENT')

    def test_frozen_and_out_of_order_health_not_unfrozen_or_overwritten(self):
        old={'status':'FROZEN','observed_at':'3','consecutive_failures':3}
        good={'status':'success','records':2,'ean_records':2}
        self.assertEqual(health_update(old,good,mode='ean',run_id='1',observed_at='1'),old)
        self.assertEqual(health_update(old,good,mode='ean',run_id='4',observed_at='4')['status'],'FROZEN')

    def test_single_health_update_preserves_source_rows_and_other_mode(self):
        text = 'SOURCE ROWS\n<!-- quality-gate:start -->\n| shop.example | 1 | APPROVED | 0 | 20 | 2/3 | ACTIVE | ACTIVE | proof |\n<!-- quality-gate:end -->\n'
        changed = update_health_cell(text, 'shop.example', 'ean', {'status':'INCIDENT','last_run_id':'123'})
        self.assertTrue(changed.startswith('SOURCE ROWS\n'))
        self.assertIn('| ACTIVE | INCIDENT (run 123) | proof |', changed)
        self.assertEqual(update_health_cell(changed,'other.example','price',{'status':'ACTIVE'}),changed)

    def test_daily_ean_reservations_cap_repeats_and_reset_by_day(self):
        state, first = reserve_budget({},'a',100,'2026-10-18')
        state, second = reserve_budget(state,'b',200,'2026-10-18')
        self.assertEqual((first,second),(100,150))
        state, duplicate = reserve_budget(state,'b',200,'2026-10-18')
        self.assertEqual((state['reserved'],duplicate),(250,150))
        state, empty = reserve_budget(state,'c',25,'2026-10-18')
        self.assertEqual(empty,0)
        state, next_day = reserve_budget(state,'d',250,'2026-10-19')
        self.assertEqual(next_day,250)

    def test_credentials_rejected(self):
        with patch.dict(os.environ,{'GH_TOKEN':'test-not-a-real-token'},clear=True):
            with self.assertRaises(CollectionBlocked):gate.run_batch(Path('unused'),Path('unused'))


if __name__=='__main__':unittest.main()
